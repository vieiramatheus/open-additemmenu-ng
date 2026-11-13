# SPDX-License-Identifier: GPL-3.0-or-later
#
# CommonLibSSE-NG, pinned to one release and built from source as part of this project.
#
# The release's source archive leaves out its openvr git submodule, so the openvr files the
# library needs for its VR support (the headers and openvr_api.lib) come from the openvr commit
# the release pins, downloaded separately and copied into place before the library is added.
#
# Each release also publishes a prebuilt library. AIM_COMMONLIB_PREBUILT links it instead of
# compiling CommonLibSSE-NG, but that only works when your MSVC major.minor version matches the
# one that built it (v16.4.0's was MSVC 19.51, from Visual Studio 2026). Otherwise the library's
# own cmake/Prebuilt.cmake falls back to the source build.
#
# To move to a newer release, update AIM_COMMONLIB_TAG, AIM_OPENVR_COMMIT (the extern/openvr
# submodule commit of that release) and the three SHA-256 values. The release page lists the
# prebuilt asset's; the two source archives' have to be computed after downloading them.

include(FetchContent)

set(AIM_COMMONLIB_TAG "v16.4.0")
set(AIM_OPENVR_COMMIT "60eb187801956ad277f1cae6680e3a410ee0873b")
set(_commonlib_github "https://github.com/alandtse/CommonLibSSE-NG")

# SOURCE_SUBDIR names a folder without a CMakeLists.txt, so FetchContent_MakeAvailable only
# downloads these two; the library is added further down, once its openvr files are in place.
FetchContent_Declare(
	commonlibsse
	URL "${_commonlib_github}/archive/refs/tags/${AIM_COMMONLIB_TAG}.tar.gz"
	URL_HASH SHA256=b1d5ee92f46613e61749c210f1ac86b6b63ceb115e6ab00760188409034dd38b
	SOURCE_SUBDIR include
)
FetchContent_Declare(
	openvr
	URL "https://github.com/ValveSoftware/openvr/archive/${AIM_OPENVR_COMMIT}.tar.gz"
	URL_HASH SHA256=bf41cda072173cc37b1077e991f98c7e079e5b237f194cbae43bd34a376965d2
	SOURCE_SUBDIR headers
)
FetchContent_MakeAvailable(commonlibsse openvr)

file(COPY "${openvr_SOURCE_DIR}/headers/" DESTINATION "${commonlibsse_SOURCE_DIR}/extern/openvr/headers")
file(COPY "${openvr_SOURCE_DIR}/lib/win64/openvr_api.lib" DESTINATION "${commonlibsse_SOURCE_DIR}/extern/openvr/lib/win64")

option(AIM_COMMONLIB_PREBUILT "Link the release's prebuilt CommonLibSSE-NG (needs the MSVC version that built it)" OFF)
if(AIM_COMMONLIB_PREBUILT)
	FetchContent_Declare(
		commonlibsse_prebuilt
		URL "${_commonlib_github}/releases/download/${AIM_COMMONLIB_TAG}/commonlibsse-ng-prebuilt-${AIM_COMMONLIB_TAG}-all-msvc-cmake.zip"
		URL_HASH SHA256=4057d99a56b666f87f3094cbcc8dea463e7fe0f95f73e624055a2064c608c47e
	)
	FetchContent_MakeAvailable(commonlibsse_prebuilt)
	set(COMMONLIB_PREBUILT_DIR "${commonlibsse_prebuilt_SOURCE_DIR}")
endif()

# Library options. Every runtime on: one DLL for SE (1.5.97), AE (1.6 and 1.7) and VR. The rest
# keeps the build lean: no library tests, no link-time optimization (much faster links), and no
# trampoline patch checks (this plugin doesn't patch game code).
set(ENABLE_SKYRIM_SE ON)
set(ENABLE_SKYRIM_AE ON)
set(ENABLE_SKYRIM_VR ON)
set(BUILD_TESTS OFF)
set(COMMONLIB_ENABLE_IPO OFF)
set(SKSE_SUPPORT_PATCH_SAFETY OFF)

# The sources may be shared between build folders (FETCHCONTENT_BASE_DIR); the compiled library
# goes into this build folder.
add_subdirectory("${commonlibsse_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/commonlibsse")

# add_commonlibsse_plugin(), which writes the plugin's SKSE declaration. The library includes it
# itself only when it links the prebuilt library.
if(NOT COMMAND add_commonlibsse_plugin)
	include("${commonlibsse_SOURCE_DIR}/cmake/CommonLibSSE.cmake")
endif()
