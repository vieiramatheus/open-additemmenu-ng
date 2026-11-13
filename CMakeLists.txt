# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.25)

project(
	open-additemmenu-ng
	VERSION 0.1.0
	DESCRIPTION "Replacement for AddItemMenuSE.dll, the SKSE plugin of AddItemMenu 1.14"
	LANGUAGES CXX
)

if(PROJECT_SOURCE_DIR STREQUAL PROJECT_BINARY_DIR)
	message(FATAL_ERROR "Build in a separate folder: use a preset, for example 'cmake --preset release'.")
endif()

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Debug information in every configuration, so release builds come with a PDB for crash logs.
# Embedded (/Z7) keeps it in each object file, which parallel builds handle without conflicts;
# the linker still writes the DLL's PDB.
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT Embedded)

include(cmake/commonlib.cmake)

# Compiler and linker settings shared by both plugins.
function(aim_plugin_settings TARGET)
	target_precompile_headers("${TARGET}" PRIVATE "${PROJECT_SOURCE_DIR}/src/PCH.h")
	target_compile_options(
		"${TARGET}" PRIVATE
		/W4
		/permissive-
		/utf-8
		/Zc:__cplusplus
		/external:anglebrackets
		/external:W0
	)
	target_link_options("${TARGET}" PRIVATE /DEBUG:FULL /OPT:REF /OPT:ICF)
endfunction()

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
)
aim_plugin_settings(AddItemMenuSE)

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
