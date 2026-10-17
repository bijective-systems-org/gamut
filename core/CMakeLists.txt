cmake_minimum_required(VERSION 3.16)
project(mestra_core VERSION 1.0.0 LANGUAGES C CXX)

# The shared core of spec version 1: one C++ library behind a plain C
# interface (include/mestra/mestra.h).  Python, MATLAB and Julia bind to
# that interface; nothing else is exported.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

option(MESTRA_BUILD_TESTS "Build the core's unit tests" ON)
option(MESTRA_SANITIZE "Build with the address and undefined sanitizers" OFF)

# No multiply and add may fuse into one rounding step: the built-in
# nearest-neighbour model must give bit-identical distances everywhere.
if(MSVC)
  set(MESTRA_WARNINGS /W4 /permissive-)
  set(MESTRA_FP_FLAGS /fp:precise)
else()
  set(MESTRA_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion
                      -Wsign-conversion)
  set(MESTRA_FP_FLAGS -ffp-contract=off)
endif()
set(MESTRA_SANITIZER_FLAGS "")
if(MESTRA_SANITIZE)
  set(MESTRA_SANITIZER_FLAGS -fsanitize=address,undefined
                             -fno-omit-frame-pointer
                             -fno-sanitize-recover=undefined)
  add_link_options(-fsanitize=address,undefined)
endif()

find_package(HDF5 REQUIRED COMPONENTS C HL)
find_package(ZLIB REQUIRED)
find_package(Threads REQUIRED)

set(MESTRA_CORE_SOURCES
  src/types.cpp
  src/names.cpp
  src/units.cpp
  src/sha256.cpp
  src/h5.cpp
  src/chunk.cpp
  src/schema.cpp
  src/reader.cpp
  src/writer.cpp
  src/parallel.cpp
  src/validate.cpp
  src/capi.cpp
)

# The objects once, linked into the shared library the bindings load and
# into the unit tests, which reach the internals directly.
add_library(mestra_core_objects OBJECT ${MESTRA_CORE_SOURCES})
set_target_properties(mestra_core_objects PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(mestra_core_objects
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
         ${HDF5_INCLUDE_DIRS})
target_compile_definitions(mestra_core_objects PRIVATE MESTRA_BUILDING ${HDF5_DEFINITIONS})
target_compile_options(mestra_core_objects PRIVATE ${MESTRA_WARNINGS}
                       ${MESTRA_FP_FLAGS} ${MESTRA_SANITIZER_FLAGS})

add_library(mestra SHARED $<TARGET_OBJECTS:mestra_core_objects>)
target_include_directories(mestra PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(mestra PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES} ZLIB::ZLIB
                      Threads::Threads)
set_target_properties(mestra PROPERTIES OUTPUT_NAME mestra)

if(MESTRA_BUILD_TESTS)
  enable_testing()
  add_executable(core_unit_tests tests/unit_tests.cpp $<TARGET_OBJECTS:mestra_core_objects>)
  target_include_directories(core_unit_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src ${HDF5_INCLUDE_DIRS})
  target_compile_definitions(core_unit_tests PRIVATE ${HDF5_DEFINITIONS})
  target_compile_options(core_unit_tests PRIVATE ${MESTRA_WARNINGS}
                         ${MESTRA_FP_FLAGS} ${MESTRA_SANITIZER_FLAGS})
  target_link_libraries(core_unit_tests PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES}
                        ZLIB::ZLIB Threads::Threads)
  add_test(NAME core_unit_tests COMMAND core_unit_tests
           WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})
  add_executable(core_writer_reader_tests tests/writer_reader_tests.cpp
                 $<TARGET_OBJECTS:mestra_core_objects>)
  target_include_directories(core_writer_reader_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src ${HDF5_INCLUDE_DIRS})
  target_compile_definitions(core_writer_reader_tests PRIVATE ${HDF5_DEFINITIONS})
  target_compile_options(core_writer_reader_tests PRIVATE ${MESTRA_WARNINGS}
                         ${MESTRA_FP_FLAGS} ${MESTRA_SANITIZER_FLAGS})
  target_link_libraries(core_writer_reader_tests PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES}
                        ZLIB::ZLIB Threads::Threads)
  add_test(NAME core_writer_reader_tests COMMAND core_writer_reader_tests
           WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})
endif()
