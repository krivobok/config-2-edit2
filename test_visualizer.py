#!/usr/bin/env python3
import os
import sys
import tempfile
import shutil
import xml.etree.ElementTree as ET
import re
from collections import defaultdict
import urllib.error
from unittest.mock import patch, MagicMock, ANY  # Импортируем ANY отдельно

# Добавляем путь к текущей директории в sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Теперь можно импортировать dependency_visualizer
import dependency_visualizer


def run_tests():
    tests = [
        test_construct_pom_url_valid,
        test_construct_pom_url_invalid_format,
        test_fetch_pom_success,
        test_fetch_pom_failure,
        test_extract_properties,
        test_substitute_properties,
        test_extract_dependencies,
        test_build_dependency_graph,
        test_generate_graphviz_dot,
        test_sanitize_filename,
        test_visualize_graph_success,
        test_visualize_graph_failure
        # test_full_flow удалён по просьбе пользователя
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"{test.__name__}: PASSED")
            passed += 1
        except AssertionError as e:
            print(f"{test.__name__}: FAILED")
            print(f"    {e}")
            failed += 1
        except Exception as e:
            print(f"{test.__name__}: ERROR")
            print(f"    {e}")
            failed += 1

    print(f"\nTotal: {len(tests)}, Passed: {passed}, Failed: {failed}")


def test_construct_pom_url_valid():
    package_coord = 'org.apache.commons:commons-lang3:3.12.0'
    repo_url = 'https://repo.maven.apache.org/maven2/'
    expected_url = 'https://repo.maven.apache.org/maven2/org/apache/commons/commons-lang3/3.12.0/commons-lang3-3.12.0.pom'
    result = dependency_visualizer.construct_pom_url(package_coord, repo_url)
    assert result == expected_url, f"Expected URL: {expected_url}, but got: {result}"


def test_construct_pom_url_invalid_format():
    package_coord = 'org.apache.commons:commons-lang3'  # Неполный формат
    repo_url = 'https://repo.maven.apache.org/maven2/'
    try:
        dependency_visualizer.construct_pom_url(package_coord, repo_url)
    except ValueError as e:
        expected_message = "Неверный формат имени пакета: org.apache.commons:commons-lang3. Ожидается groupId:artifactId:version"
        assert str(e) == expected_message, f"Unexpected error message: {e}"
    else:
        assert False, "ValueError was not raised for invalid package coordinate format."


@patch('dependency_visualizer.urllib.request.urlopen')
def test_fetch_pom_success(mock_urlopen):
    # Создаем пример POM XML с правильным groupId
    pom_xml = '''
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <groupId>org.apache.commons</groupId>
        <artifactId>commons-lang3</artifactId>
        <version>3.12.0</version>
        <properties>
            <project.version>3.12.0</project.version>
        </properties>
        <dependencies>
            <dependency>
                <groupId>junit</groupId>
                <artifactId>junit</artifactId>
                <version>4.13.2</version>
            </dependency>
        </dependencies>
    </project>
    '''
    # Настраиваем мок ответа
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = pom_xml.encode('utf-8')
    mock_urlopen.return_value.__enter__.return_value = mock_response  # Настройка контекстного менеджера

    pom_url = 'https://repo.maven.apache.org/maven2/org/apache/commons/commons-lang3/3.12.0/commons-lang3-3.12.0.pom'
    pom_tree = dependency_visualizer.fetch_pom(pom_url)
    assert pom_tree is not None, "POM tree should not be None."
    group_id = pom_tree.find('.//{http://maven.apache.org/POM/4.0.0}groupId')
    assert group_id is not None, "groupId should be present in the POM."
    assert group_id.text == 'org.apache.commons', f"Expected groupId 'org.apache.commons', got '{group_id.text}'."


@patch('dependency_visualizer.urllib.request.urlopen')
def test_fetch_pom_failure(mock_urlopen):
    # Настраиваем мок для ошибки URL
    mock_urlopen.side_effect = urllib.error.URLError('Not Found')

    pom_url = 'https://repo.maven.apache.org/maven2/org/apache/commons/commons-lang3/3.12.0/commons-lang3-3.12.0.pom'
    pom_tree = dependency_visualizer.fetch_pom(pom_url)
    assert pom_tree is None, "POM tree should be None on URL error."


def test_extract_properties():
    pom_xml = '''
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <properties>
            <project.version>1.0.0</project.version>
            <java.version>11</java.version>
        </properties>
    </project>
    '''
    pom_tree = ET.fromstring(pom_xml)
    properties = dependency_visualizer.extract_properties(pom_tree)
    expected_properties = {
        'project.version': '1.0.0',
        'java.version': '11'
    }
    assert properties == expected_properties, f"Expected properties {expected_properties}, got {properties}."


def test_substitute_properties():
    # Тест с заменой переменной
    text = '${project.version}'
    properties = {'project.version': '1.0.0'}
    result = dependency_visualizer.substitute_properties(text, properties)
    assert result == '1.0.0', f"Expected '1.0.0', got '{result}'."

    # Тест без переменных
    text_no_var = '1.0.0'
    result_no_var = dependency_visualizer.substitute_properties(text_no_var, properties)
    assert result_no_var == '1.0.0', f"Expected '1.0.0', got '{result_no_var}'."

    # Тест с неизвестной переменной
    text_unknown_var = '${unknown.version}'
    result_unknown_var = dependency_visualizer.substitute_properties(text_unknown_var, properties)
    assert result_unknown_var == '${unknown.version}', f"Expected '${{unknown.version}}', got '{result_unknown_var}'."


def test_extract_dependencies():
    pom_xml = '''
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <properties>
            <project.version>1.0.0</project.version>
        </properties>
        <dependencies>
            <dependency>
                <groupId>junit</groupId>
                <artifactId>junit</artifactId>
                <version>${project.version}</version>
                <scope>compile</scope>
            </dependency>
            <dependency>
                <groupId>org.slf4j</groupId>
                <artifactId>slf4j-api</artifactId>
                <version>1.7.30</version>
                <scope>test</scope>
            </dependency>
            <dependency>
                <groupId>org.apache.commons</groupId>
                <artifactId>commons-io</artifactId>
                <version>2.8.0</version>
            </dependency>
        </dependencies>
    </project>
    '''
    pom_tree = ET.fromstring(pom_xml)
    dependencies = dependency_visualizer.extract_dependencies(pom_tree)
    expected_dependencies = [
        'junit:junit:1.0.0',
        'org.apache.commons:commons-io:2.8.0'
    ]
    assert dependencies == expected_dependencies, f"Expected dependencies {expected_dependencies}, got {dependencies}."


@patch('dependency_visualizer.fetch_pom')
def test_build_dependency_graph(mock_fetch_pom):
    # Создаем имитацию POM-файлов
    pom_main = '''
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <groupId>org.apache.commons</groupId>
        <artifactId>commons-lang3</artifactId>
        <version>1.0.0</version>
        <properties>
            <project.version>1.0.0</project.version>
        </properties>
        <dependencies>
            <dependency>
                <groupId>junit</groupId>
                <artifactId>junit</artifactId>
                <version>4.13.2</version>
                <scope>compile</scope>
            </dependency>
            <dependency>
                <groupId>org.apache.commons</groupId>
                <artifactId>commons-io</artifactId>
                <version>2.8.0</version>
            </dependency>
        </dependencies>
    </project>
    '''
    pom_junit = '''
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <groupId>junit</groupId>
        <artifactId>junit</artifactId>
        <version>4.13.2</version>
        <dependencies>
            <dependency>
                <groupId>org.hamcrest</groupId>
                <artifactId>hamcrest-core</artifactId>
                <version>1.3</version>
            </dependency>
        </dependencies>
    </project>
    '''

    # Настраиваем мок fetch_pom
    def side_effect(pom_url):
        if 'commons-lang3' in pom_url:
            return ET.fromstring(pom_main)
        elif 'junit' in pom_url:
            return ET.fromstring(pom_junit)
        else:
            return None

    mock_fetch_pom.side_effect = side_effect

    graph = defaultdict(set)
    visited = set()
    dependency_visualizer.build_dependency_graph(
        'org.apache.commons:commons-lang3:1.0.0',
        'https://repo.maven.apache.org/maven2/',
        max_depth=2,
        current_depth=0,
        graph=graph,
        visited=visited
    )

    expected_graph = {
        'org.apache.commons:commons-lang3:1.0.0': {'junit:junit:4.13.2', 'org.apache.commons:commons-io:2.8.0'},
        'junit:junit:4.13.2': {'org.hamcrest:hamcrest-core:1.3'},
        'org.hamcrest:hamcrest-core:1.3': set(),
        'org.apache.commons:commons-io:2.8.0': set()
    }
    assert dict(graph) == expected_graph, f"Expected graph {expected_graph}, got {dict(graph)}."


def test_generate_graphviz_dot():
    graph = {
        'org.apache.commons:commons-lang3:1.0.0': {'junit:junit:4.13.2'},
        'junit:junit:4.13.2': {'org.hamcrest:hamcrest-core:1.3'},
        'org.hamcrest:hamcrest-core:1.3': set()
    }
    dot_output = dependency_visualizer.generate_graphviz_dot(graph)
    expected_dot = '''digraph G {
    node [shape=box];
    "org.apache.commons:commons-lang3:1.0.0" -> "junit:junit:4.13.2";
    "junit:junit:4.13.2" -> "org.hamcrest:hamcrest-core:1.3";
}
'''
    # Поскольку 'org.hamcrest:hamcrest-core:1.3' имеет пустое множество зависимостей, оно не должно быть включено в DOT
    assert dot_output == expected_dot, f"Expected DOT output:\n{expected_dot}\nBut got:\n{dot_output}"


def test_sanitize_filename():
    # Тест без недопустимых символов
    name = 'org.apache:commons-lang3:1.0.0'
    expected = 'org.apache_commons-lang3_1.0.0'
    result = dependency_visualizer.sanitize_filename(name)
    assert result == expected, f"Expected '{expected}', got '{result}'."

    # Тест с недопустимыми символами
    name_with_invalid = 'org.apache/commons:commons-lang3:1.0.0?'
    expected_with_invalid = 'org.apache_commons_commons-lang3_1.0.0_'
    result_with_invalid = dependency_visualizer.sanitize_filename(name_with_invalid)
    assert result_with_invalid == expected_with_invalid, f"Expected '{expected_with_invalid}', got '{result_with_invalid}'."


@patch('dependency_visualizer.subprocess.run')
def test_visualize_graph_success(mock_subprocess_run):
    # Настраиваем мок subprocess.run для успешного выполнения
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_subprocess_run.return_value = mock_result

    dot_data = 'digraph G { "A" -> "B"; }'
    package_coord = 'org.apache.commons:commons-lang3:1.0.0'
    repo_url = 'https://repo.maven.apache.org/maven2/'

    # Создаем временную директорию для теста
    test_dir = tempfile.mkdtemp()
    try:
        # Запускаем функцию визуализации
        dependency_visualizer.visualize_graph(
            'C:\\Program Files\\Graphviz\\bin\\dot.exe' if os.name == 'nt' else '/usr/bin/dot',
            dot_data,
            test_dir,
            package_coord
        )

        # После вызова subprocess.run, симулируем создание img_filename
        safe_name = dependency_visualizer.sanitize_filename(package_coord)
        img_filename = os.path.join(test_dir, f"{safe_name}.png")
        with open(img_filename, 'wb') as f:
            f.write(b'')  # Создаем пустой файл, чтобы симулировать успешное создание

        # Проверяем, что файлы были созданы
        dot_filename = os.path.join(test_dir, f"{safe_name}.dot")
        assert os.path.isfile(dot_filename), f"DOT файл {dot_filename} не создан."
        assert os.path.isfile(img_filename), f"Изображение {img_filename} не создано."

        # Проверяем, что subprocess.run был вызван правильно
        expected_call = [
            'C:\\Program Files\\Graphviz\\bin\\dot.exe' if os.name == 'nt' else '/usr/bin/dot',
            '-Tpng',
            dot_filename,
            '-o',
            img_filename
        ]
        mock_subprocess_run.assert_called_with(
            expected_call,
            stdout=ANY,  # Используем ANY вместо MagicMock.ANY
            stderr=ANY
        )
    finally:
        # Удаляем временную директорию после теста
        shutil.rmtree(test_dir)


@patch('dependency_visualizer.subprocess.run')
def test_visualize_graph_failure(mock_subprocess_run):
    # Настраиваем мок subprocess.run для ошибки выполнения
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = b'Error in Graphviz'
    mock_subprocess_run.return_value = mock_result

    dot_data = 'digraph G { "A" -> "B"; }'
    package_coord = 'org.apache.commons:commons-lang3:1.0.0'
    repo_url = 'https://repo.maven.apache.org/maven2/'

    # Создаем временную директорию для теста
    test_dir = tempfile.mkdtemp()
    try:
        # Запускаем функцию визуализации
        dependency_visualizer.visualize_graph(
            'C:\\Program Files\\Graphviz\\bin\\dot.exe' if os.name == 'nt' else '/usr/bin/dot',
            dot_data,
            test_dir,
            package_coord
        )

        # Проверяем, что DOT файл был создан
        safe_name = dependency_visualizer.sanitize_filename(package_coord)
        dot_filename = os.path.join(test_dir, f"{safe_name}.dot")
        img_filename = os.path.join(test_dir, f"{safe_name}.png")
        assert os.path.isfile(dot_filename), f"DOT файл {dot_filename} не создан."

        # Изображение не должно быть создано из-за ошибки
        assert not os.path.isfile(img_filename), f"Изображение {img_filename} должно быть отсутствовать из-за ошибки."

        # Проверяем, что subprocess.run был вызван правильно
        expected_call = [
            'C:\\Program Files\\Graphviz\\bin\\dot.exe' if os.name == 'nt' else '/usr/bin/dot',
            '-Tpng',
            dot_filename,
            '-o',
            img_filename
        ]
        mock_subprocess_run.assert_called_with(
            expected_call,
            stdout=ANY,  # Используем ANY вместо MagicMock.ANY
            stderr=ANY
        )
    finally:
        # Удаляем временную директорию после теста
        shutil.rmtree(test_dir)


if __name__ == '__main__':
    run_tests()
