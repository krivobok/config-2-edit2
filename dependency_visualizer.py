#!/usr/bin/env python3
import argparse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import subprocess
import os
import sys
from collections import defaultdict
import re

def parse_arguments():
    parser = argparse.ArgumentParser(description="Визуализатор графа зависимостей Maven-пакетов.")
    parser.add_argument('--graphviz', required=True, help='Путь к программе для визуализации графов (например, /usr/bin/dot)')
    parser.add_argument('--package', required=True, help='Имя анализируемого пакета в формате groupId:artifactId:version')
    parser.add_argument('--depth', type=int, required=True, help='Максимальная глубина анализа зависимостей')
    parser.add_argument('--repo', required=True, help='URL-адрес Maven-репозитория (например, https://repo.maven.apache.org/maven2/)')
    parser.add_argument('--output', default='.', help='Путь к папке для сохранения файлов (по умолчанию текущая директория)')
    return parser.parse_args()

def construct_pom_url(package_coord, repo_url):
    """
    Формирует URL для POM-файла на основе координат пакета и URL репозитория.
    """
    parts = package_coord.split(':')
    if len(parts) != 3:
        raise ValueError(f"Неверный формат имени пакета: {package_coord}. Ожидается groupId:artifactId:version")
    group_id, artifact_id, version = parts
    group_path = group_id.replace('.', '/')
    pom_filename = f"{artifact_id}-{version}.pom"
    pom_url = f"{repo_url.rstrip('/')}/{group_path}/{artifact_id}/{version}/{pom_filename}"
    return pom_url

def fetch_pom(pom_url):
    """
    Загружает POM-файл по заданному URL и возвращает объект ElementTree.
    """
    try:
        with urllib.request.urlopen(pom_url) as response:
            if response.status != 200:
                return None
            data = response.read()
            return ET.fromstring(data)
    except urllib.error.URLError:
        return None
    except ET.ParseError:
        return None

def extract_properties(pom_tree):
    """
    Извлекает свойства из POM-файла.
    Возвращает словарь свойств.
    """
    properties = {}
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    properties_nodes = pom_tree.findall('.//m:properties/*', ns)
    if not properties_nodes:
        properties_nodes = pom_tree.findall('.//properties/*')
    for prop in properties_nodes:
        tag = prop.tag
        # Удаление пространства имен, если есть
        if '}' in tag:
            tag = tag.split('}', 1)[1]
        if prop.text:
            properties[tag] = prop.text.strip()
    return properties

def substitute_properties(text, properties):
    """
    Заменяет переменные в тексте на значения из свойств.
    Пример: ${project.version} -> значение из properties['project.version']
    """
    pattern = re.compile(r'\$\{([^}]+)\}')

    def replacer(match):
        var_name = match.group(1)
        return properties.get(var_name, match.group(0))  # Оставить как есть, если не найдено

    return pattern.sub(replacer, text)

def extract_dependencies(pom_tree):
    """
    Извлекает зависимости из POM-файла.
    Возвращает список координат зависимостей в формате groupId:artifactId:version.
    """
    dependencies = []
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    # Некоторые POM-файлы могут не иметь пространств имен
    dependency_nodes = pom_tree.findall('.//m:dependencies/m:dependency', ns)
    if not dependency_nodes:
        dependency_nodes = pom_tree.findall('.//dependencies/dependency')
    properties = extract_properties(pom_tree)
    for dep in dependency_nodes:
        group_id = dep.find('m:groupId', ns)
        artifact_id = dep.find('m:artifactId', ns)
        version = dep.find('m:version', ns)
        scope = dep.find('m:scope', ns)
        
        # Игнорируем зависимости с scope test, provided, etc.
        if scope is not None and scope.text.strip() not in ('compile', 'runtime', 'system'):
            continue

        if group_id is None or artifact_id is None:
            continue  # Пропустить неполные зависимости
        group_id_text = group_id.text.strip() if group_id.text else ''
        artifact_id_text = artifact_id.text.strip() if artifact_id.text else ''
        version_text = version.text.strip() if version is not None and version.text else None

        if version_text:
            # Заменяем переменные в версии, если они есть
            version_text = substitute_properties(version_text, properties)
        
        if version_text is None:
            continue  # Пропустить зависимости с неопределенной версией

        dep_coord = f"{group_id_text}:{artifact_id_text}:{version_text}"
        dependencies.append(dep_coord)
    return dependencies

def build_dependency_graph(package_coord, repo_url, max_depth, current_depth, graph, visited):
    """
    Рекурсивно строит граф зависимостей.
    """
    if current_depth > max_depth:
        return
    if package_coord in visited:
        return
    visited.add(package_coord)
    pom_url = construct_pom_url(package_coord, repo_url)
    pom_tree = fetch_pom(pom_url)
    if pom_tree is None:
        # Добавляем узел без дальнейшей рекурсии
        graph[package_coord]  # Создает ключ с пустым множеством, если его нет
        return
    dependencies = extract_dependencies(pom_tree)
    for dep in dependencies:
        graph[package_coord].add(dep)
        build_dependency_graph(dep, repo_url, max_depth, current_depth + 1, graph, visited)

def generate_graphviz_dot(graph):
    """
    Генерирует строку в формате DOT для Graphviz на основе графа зависимостей.
    """
    dot = "digraph G {\n"
    dot += "    node [shape=box];\n"
    for parent, children in graph.items():
        parent_sanitized = parent.replace('"', '\\"')
        for child in children:
            child_sanitized = child.replace('"', '\\"')
            dot += f'    "{parent_sanitized}" -> "{child_sanitized}";\n'
    dot += "}\n"
    return dot

def sanitize_filename(name):
    """
    Заменяет недопустимые символы в имени файла на подчеркивания.
    """
    return re.sub(r'[\\/:*?"<>|]', '_', name)

def visualize_graph(graphviz_path, dot_data, output_dir, package_coord):
    """
    Генерирует изображение графа с помощью Graphviz и сохраняет его в указанной папке.
    """
    # Создаем безопасное имя файла на основе координат пакета
    safe_name = sanitize_filename(package_coord)
    dot_filename = os.path.join(output_dir, f"{safe_name}.dot")
    img_filename = os.path.join(output_dir, f"{safe_name}.png")

    # Сохраняем DOT данные
    with open(dot_filename, 'w', encoding='utf-8') as f:
        f.write(dot_data)

    # Формируем команду для Graphviz
    cmd = [graphviz_path, '-Tpng', dot_filename, '-o', img_filename]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        # Если Graphviz завершился с ошибкой, ничего не выводим
        return

    # Выводим только сообщения о создании файлов
    print(f"DOT-файл сохранен: {dot_filename}")
    print(f"Изображение графа сохранено: {img_filename}")

    # Если хотите удалить DOT-файл после создания изображения, раскомментируйте строку ниже
    # os.remove(dot_filename)

def main():
    args = parse_arguments()
    package_coord = args.package
    graphviz_path = args.graphviz
    max_depth = args.depth
    repo_url = args.repo
    output_dir = args.output

    # Проверка существования Graphviz
    if not os.path.isfile(graphviz_path) or not os.access(graphviz_path, os.X_OK):
        sys.exit(1)  # Выход без вывода

    # Проверка существования выходной директории
    if not os.path.isdir(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception:
            sys.exit(1)  # Выход без вывода

    graph = defaultdict(set)
    visited = set()

    build_dependency_graph(package_coord, repo_url, max_depth, 0, graph, visited)

    dot_data = generate_graphviz_dot(graph)

    visualize_graph(graphviz_path, dot_data, output_dir, package_coord)

if __name__ == "__main__":
    main()
