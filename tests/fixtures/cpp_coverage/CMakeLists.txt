cmake_minimum_required(VERSION 3.16)
project(cpp_coverage_fixture LANGUAGES CXX)

enable_testing()
add_library(core src/core.cpp)
target_include_directories(core PUBLIC include)
target_compile_options(core PUBLIC --coverage)
target_link_options(core PUBLIC --coverage)

add_executable(test_positive tests/test_positive.cpp)
target_link_libraries(test_positive PRIVATE core)
add_test(NAME positive COMMAND test_positive)
