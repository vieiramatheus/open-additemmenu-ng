# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.25)

# The unit tests need Catch2, which vcpkg installs with the manifest's "tests" feature. That has
# to be chosen before project(), where vcpkg runs.
option(AIM_BUILD_TESTS "Build the unit tests" ON)
if(AIM_BUILD_TESTS)
	list(APPEND VCPKG_MANIFEST_FEATURES "tests")
endif()

project(
	open-additemmenu-ng
	VERSION 1.0.0
	DESCRIPTION "Replacement for AddItemMenuSE.dll, the SKSE plugin of AddItemMenu 1.14"
	LANGUAGES CXX RC
)

if(PROJECT_SOURCE_DIR STREQUAL PROJECT_BINARY_DIR)
	message(FATAL_ERROR "Build in a separate folder: use a preset, for example 'cmake --preset release'.")
endif()

# The release's name. SKSE only takes numbers (PROJECT_VERSION, reported as 1.0.0.0), so a label
# such as "beta-release" goes in the DLL's file properties, the archive and the FOMOD. Keep
# "version-semver" in vcpkg.json the same: tools/package.py checks that the two agree.
set(AIM_RELEASE_LABEL "beta-release")
set(AIM_RELEASE_NAME "${PROJECT_VERSION}")
if(AIM_RELEASE_LABEL)
	string(APPEND AIM_RELEASE_NAME "-${AIM_RELEASE_LABEL}")
endif()

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Debug information in every configuration, so release builds come with a PDB for crash logs.
# Embedded (/Z7) keeps it in each object file, which parallel builds handle without conflicts;
# the linker still writes the DLL's PDB.
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT Embedded)

include(cmake/commonlib.cmake)

set(AIM_WARNINGS /W4 /permissive- /utf-8 /Zc:__cplusplus /external:anglebrackets /external:W0)

# Compiler and linker settings shared by both plugins.
function(aim_plugin_settings TARGET)
	target_precompile_headers("${TARGET}" PRIVATE "${PROJECT_SOURCE_DIR}/src/PCH.h")
	target_compile_options("${TARGET}" PRIVATE ${AIM_WARNINGS})
	target_link_options("${TARGET}" PRIVATE /DEBUG:FULL /OPT:REF /OPT:ICF)
endfunction()

# ---------------------------------------------------------------------------------------
# aim_core: the parts that don't need the game (settings, translations, the text functions and
# the menu's entries), shared by the DLL and the unit tests.

add_library(
	aim_core STATIC
	src/core/Files.cpp
	src/core/Menu.cpp
	src/core/Settings.cpp
	src/core/Text.cpp
	src/core/Translations.cpp
)
target_include_directories(aim_core PUBLIC "${PROJECT_SOURCE_DIR}/src")
target_compile_options(aim_core PRIVATE ${AIM_WARNINGS})

# ---------------------------------------------------------------------------------------
# AddItemMenuSE.dll

add_commonlibsse_plugin(
	AddItemMenuSE
	NAME "AddItemMenuSE"
	AUTHOR "open-additemmenu-ng"
	VERSION "${PROJECT_VERSION}"
	USE_ADDRESS_LIBRARY
	SOURCES
		src/main.cpp
		src/game/Clipboard.cpp
		src/game/Index.cpp
		src/game/Papyrus.cpp
		src/game/State.cpp
)
aim_plugin_settings(AddItemMenuSE)
# Clipboard.cpp includes <Windows.h>, which must not meet the CommonLibSSE-NG headers.
set_source_files_properties(src/game/Clipboard.cpp PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
target_link_libraries(AddItemMenuSE PRIVATE aim_core user32)
# The version shown in the DLL's file properties and in crash logs.
configure_file(cmake/Version.rc.in "${CMAKE_CURRENT_BINARY_DIR}/AddItemMenuSE.rc" @ONLY)
target_sources(AddItemMenuSE PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/AddItemMenuSE.rc")

# ---------------------------------------------------------------------------------------
# Unit tests: 'ctest --preset <preset>' after a build.

if(AIM_BUILD_TESTS)
	enable_testing()
	find_package(Catch2 3 CONFIG REQUIRED)
	add_executable(
		aim_tests
		tests/MenuTests.cpp
		tests/SettingsTests.cpp
		tests/TextTests.cpp
		tests/TranslationsTests.cpp
	)
	target_link_libraries(aim_tests PRIVATE aim_core Catch2::Catch2WithMain)
	target_compile_options(aim_tests PRIVATE ${AIM_WARNINGS})
	add_test(NAME aim_tests COMMAND aim_tests)
endif()

# ---------------------------------------------------------------------------------------
# AIMProbe.dll: the test plugin that calls AddItemMenuSE's functions and records the answers
# (see probe/main.cpp). It is a test tool and is never released.

add_commonlibsse_plugin(
	AIMProbe
	NAME "AIMProbe"
	AUTHOR "open-additemmenu-ng"
	VERSION "${PROJECT_VERSION}"
	USE_ADDRESS_LIBRARY
	SOURCES
		probe/main.cpp
		probe/Probe.cpp
		probe/Json.cpp
		probe/Win32.cpp
)
aim_plugin_settings(AIMProbe)
# These two include <Windows.h>, which must not meet the CommonLibSSE-NG headers.
set_source_files_properties(probe/Json.cpp probe/Win32.cpp PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
target_link_libraries(AIMProbe PRIVATE user32)

# ---------------------------------------------------------------------------------------
# 'deploy': build, then put AddItemMenuSE.dll and its PDB into a test install through
# tools/deploy.py, as the package 'additemmenu-ng'. That package goes on top of whatever
# AddItemMenuSE.dll is installed there, and 'deploy.py uninstall additemmenu-ng' brings it back.
# A plain build never touches the game.

set(AIM_DEPLOY_STATE "" CACHE PATH "State folder of the test install that the 'deploy' target updates (see tools/deploy.py)")
if(AIM_DEPLOY_STATE)
	find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
	add_custom_target(
		deploy
		COMMAND "${Python3_EXECUTABLE}" -B "${PROJECT_SOURCE_DIR}/tools/deploy.py"
			--state "${AIM_DEPLOY_STATE}"
			swap additemmenu-ng
			--file "$<TARGET_FILE:AddItemMenuSE>" "game:Data/SKSE/Plugins/AddItemMenuSE.dll"
			--file "$<TARGET_PDB_FILE:AddItemMenuSE>" "game:Data/SKSE/Plugins/AddItemMenuSE.pdb"
			--note "open-additemmenu-ng ${PROJECT_VERSION}"
		COMMENT "Deploying AddItemMenuSE.dll to the test install"
		USES_TERMINAL
		VERBATIM
	)
	add_dependencies(deploy AddItemMenuSE)

	# The probe goes in as its own package, 'aimprobe'. Its settings file, which says where to
	# write the results, is put in place separately for each run.
	add_custom_target(
		deploy-probe
		COMMAND "${Python3_EXECUTABLE}" -B "${PROJECT_SOURCE_DIR}/tools/deploy.py"
			--state "${AIM_DEPLOY_STATE}"
			swap aimprobe
			--file "$<TARGET_FILE:AIMProbe>" "game:Data/SKSE/Plugins/AIMProbe.dll"
			--file "$<TARGET_PDB_FILE:AIMProbe>" "game:Data/SKSE/Plugins/AIMProbe.pdb"
			--note "AIMProbe ${PROJECT_VERSION}"
		COMMENT "Deploying AIMProbe.dll to the test install"
		USES_TERMINAL
		VERBATIM
	)
	add_dependencies(deploy-probe AIMProbe)
endif()
