cmake_minimum_required(VERSION 3.16)
project(gamut VERSION 2.0.0 LANGUAGES C CXX)

# The shared core of spec version 1: one C++ library behind a plain C
# interface (include/gamut/gamut.h).  Python, MATLAB and Julia bind to
# that interface; nothing else is exported.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

option(GAMUT_BUILD_TESTS "Build the core's unit tests" ON)
option(GAMUT_SANITIZE "Build with the address and undefined sanitizers" OFF)
# A process may hold another HDF5 (h5py's, MATLAB's).  Where symbols share
# one namespace (Linux), a core linked to a shared HDF5 can bind to the
# other copy; linked statically, with only gamut_* exported, it cannot.
option(GAMUT_STATIC_HDF5 "Link HDF5 statically into the core" OFF)
if(GAMUT_STATIC_HDF5)
  set(HDF5_USE_STATIC_LIBRARIES ON)
  set(ZLIB_USE_STATIC_LIBS ON)
  # With the C runtime linked statically, as tools/build_deps.sh builds
  # HDF5 and zlib, the DLL needs no Visual C++ redistributable.
  set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)
endif()

# No multiply and add may fuse into one rounding step: the built-in
# nearest-neighbour model must give bit-identical distances everywhere.
if(MSVC)
  set(GAMUT_WARNINGS /W4 /permissive-)
  set(GAMUT_FP_FLAGS /fp:precise)
else()
  set(GAMUT_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion
                      -Wsign-conversion)
  set(GAMUT_FP_FLAGS -ffp-contract=off)
endif()
set(GAMUT_SANITIZER_FLAGS "")
if(GAMUT_SANITIZE)
  set(GAMUT_SANITIZER_FLAGS -fsanitize=address,undefined
                             -fno-omit-frame-pointer
                             -fno-sanitize-recover=undefined)
  add_link_options(-fsanitize=address,undefined)
endif()

find_package(HDF5 REQUIRED COMPONENTS C HL)
# 1.14 brought H5Dchunk_iter, which the core's chunk index pass uses;
# packages bundle 1.14.
if(HDF5_VERSION AND HDF5_VERSION VERSION_LESS 1.14)
  message(FATAL_ERROR "the Gamut core needs HDF5 1.14 or later; found ${HDF5_VERSION}. "
                      "Point HDF5_ROOT at a newer HDF5.")
endif()
find_package(ZLIB REQUIRED)
find_package(Threads REQUIRED)

set(GAMUT_CORE_SOURCES
  src/types.cpp
  src/names.cpp
  src/units.cpp
  src/sha256.cpp
  src/h5.cpp
  src/chunk.cpp
  src/chunks.cpp
  src/schema.cpp
  src/reader.cpp
  src/writer.cpp
  src/validate.cpp
  src/value.cpp
  src/codec.cpp
  src/nearest.cpp
  src/evaluate.cpp
  src/copy.cpp
  src/select.cpp
  src/capi.cpp
)

# The objects once, linked into the shared library the bindings load and
# into the unit tests, which reach the internals directly.
add_library(gamut_core_objects OBJECT ${GAMUT_CORE_SOURCES})
set_target_properties(gamut_core_objects PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(gamut_core_objects
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
         ${HDF5_INCLUDE_DIRS})
target_compile_definitions(gamut_core_objects PRIVATE GAMUT_BUILDING ${HDF5_DEFINITIONS})
# HDF5's CMake package puts its compile definitions on its imported targets,
# not in HDF5_DEFINITIONS.  On Windows a DLL build's H5_BUILT_AS_DYNAMIC_LIB
# declares the data HDF5 exports (H5T_NATIVE_INT and the like) dllimport;
# without it the core does not link against a shared HDF5 such as conda's.
target_link_libraries(gamut_core_objects PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES})
if(GAMUT_STATIC_HDF5)
  # The core owns its HDF5, and so may set it up (no filter plugins).
  set(GAMUT_OWN_HDF5 GAMUT_OWN_HDF5)
endif()
target_compile_definitions(gamut_core_objects PRIVATE ${GAMUT_OWN_HDF5})
target_compile_options(gamut_core_objects PRIVATE ${GAMUT_WARNINGS}
                       ${GAMUT_FP_FLAGS} ${GAMUT_SANITIZER_FLAGS})

add_library(gamut SHARED $<TARGET_OBJECTS:gamut_core_objects>)
target_include_directories(gamut PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(gamut PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES} ZLIB::ZLIB
                      Threads::Threads ${CMAKE_DL_LIBS})
# Nothing but the C interface leaves the library, whatever is linked into it.
if(APPLE)
  target_link_options(gamut PRIVATE
    "LINKER:-exported_symbols_list,${CMAKE_CURRENT_SOURCE_DIR}/exports.txt")
elseif(UNIX)
  target_link_options(gamut PRIVATE "LINKER:--version-script=${CMAKE_CURRENT_SOURCE_DIR}/exports.map")
  if(NOT GAMUT_SANITIZE)
    target_link_options(gamut PRIVATE "LINKER:--no-undefined")
  endif()
endif()
set_target_properties(gamut PROPERTIES OUTPUT_NAME gamut)
# gamut.hpp needs C++17 in the programs that include it.
target_compile_features(gamut INTERFACE cxx_std_17)

if(GAMUT_BUILD_TESTS)
  enable_testing()
  add_executable(core_unit_tests tests/unit_tests.cpp $<TARGET_OBJECTS:gamut_core_objects>)
  target_include_directories(core_unit_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src ${HDF5_INCLUDE_DIRS})
  target_compile_definitions(core_unit_tests PRIVATE ${HDF5_DEFINITIONS} ${GAMUT_OWN_HDF5})
  target_compile_options(core_unit_tests PRIVATE ${GAMUT_WARNINGS}
                         ${GAMUT_FP_FLAGS} ${GAMUT_SANITIZER_FLAGS})
  target_link_libraries(core_unit_tests PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES}
                        ZLIB::ZLIB Threads::Threads)
  add_test(NAME core_unit_tests COMMAND core_unit_tests
           WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})
  add_executable(core_writer_reader_tests tests/writer_reader_tests.cpp
                 $<TARGET_OBJECTS:gamut_core_objects>)
  target_include_directories(core_writer_reader_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src ${HDF5_INCLUDE_DIRS})
  target_compile_definitions(core_writer_reader_tests PRIVATE ${HDF5_DEFINITIONS} ${GAMUT_OWN_HDF5})
  target_compile_options(core_writer_reader_tests PRIVATE ${GAMUT_WARNINGS}
                         ${GAMUT_FP_FLAGS} ${GAMUT_SANITIZER_FLAGS})
  target_link_libraries(core_writer_reader_tests PRIVATE ${HDF5_HL_LIBRARIES} ${HDF5_C_LIBRARIES}
                        ZLIB::ZLIB Threads::Threads)
  add_test(NAME core_writer_reader_tests COMMAND core_writer_reader_tests
           WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})
  # The C++ interface, linked to the shared library as a program using it is.
  add_executable(header_tests tests/header_tests.cpp)
  target_include_directories(header_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
  target_compile_options(header_tests PRIVATE ${GAMUT_WARNINGS} ${GAMUT_SANITIZER_FLAGS})
  target_link_libraries(header_tests PRIVATE gamut Threads::Threads)
  add_test(NAME header_tests COMMAND header_tests WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})
endif()

# Installing.  A Python wheel (scikit-build-core) takes the library alone,
# beside the package; otherwise the header, the library and a CMake package
# (find_package(gamut) gives gamut::gamut).  Linked to a shared HDF5
# outside the install (a source build), the library keeps the path to it.
set_target_properties(gamut PROPERTIES INSTALL_RPATH_USE_LINK_PATH TRUE)
if(SKBUILD)
  # On Windows the import library (gamut.lib) goes too, so MATLAB's gateway
  # can be built against the wheel's core.
  install(TARGETS gamut LIBRARY DESTINATION gamut/_native RUNTIME DESTINATION gamut/_native
                         ARCHIVE DESTINATION gamut/_native)
else()
  include(GNUInstallDirs)
  include(CMakePackageConfigHelpers)
  target_include_directories(gamut INTERFACE $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
  install(TARGETS gamut EXPORT gamutTargets
          LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
          ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
          RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
  install(FILES include/gamut/gamut.h include/gamut/gamut.hpp DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/gamut)
  install(EXPORT gamutTargets NAMESPACE gamut::
          DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/gamut)
  file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/gamutConfig.cmake.in
       "@PACKAGE_INIT@\ninclude(\"\${CMAKE_CURRENT_LIST_DIR}/gamutTargets.cmake\")\n")
  configure_package_config_file(${CMAKE_CURRENT_BINARY_DIR}/gamutConfig.cmake.in
                                ${CMAKE_CURRENT_BINARY_DIR}/gamutConfig.cmake
                                INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/gamut)
  write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/gamutConfigVersion.cmake
                                   COMPATIBILITY SameMajorVersion)
  install(FILES ${CMAKE_CURRENT_BINARY_DIR}/gamutConfig.cmake
                ${CMAKE_CURRENT_BINARY_DIR}/gamutConfigVersion.cmake
          DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/gamut)
endif()
