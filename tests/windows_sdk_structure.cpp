// CI-only read-only discriminator. Uses actual SDK declarations independently
// of Python ctypes. Parent kills after two seconds and bounds stdout to64KiB.
// Identities stay in memory for boolean joins; no names/geometry are emitted.
#define WINVER 0x0A00
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <cstddef>
#include <cstdio>

constexpr UINT32 max_paths = 64;
constexpr UINT32 max_modes = 192;
static const char* truth(bool value) { return value ? "true" : "false"; }
static bool matches(const DISPLAYCONFIG_MODE_INFO* modes, UINT32 count,
                    UINT32 index, DISPLAYCONFIG_MODE_INFO_TYPE kind,
                    LUID adapter, UINT32 id) {
    if (index >= count) return false;
    const auto& mode = modes[index];
    return mode.infoType == kind && mode.id == id &&
        mode.adapterId.LowPart == adapter.LowPart && mode.adapterId.HighPart == adapter.HighPart;
}
static const char* error_code(LONG code) {
    switch (code) {
    case ERROR_ACCESS_DENIED: return "WINDOWS_DESKTOP_ACCESS_UNAVAILABLE";
    case ERROR_NOT_SUPPORTED: return "WINDOWS_DRIVER_UNSUPPORTED";
    case ERROR_INVALID_PARAMETER: return "WINDOWS_API_UNSUPPORTED";
    default: return "WINDOWS_DISPLAY_QUERY_FAILED";
    }
}
static void unavailable(UINT32 flags, const char* code) {
    std::printf("{\"status\":\"QUERY_UNAVAILABLE\",\"query_flags\":%u,\"code\":\"%s\"}", flags, code);
}
static void query(UINT32 flags) {
    DISPLAYCONFIG_PATH_INFO paths[max_paths]{};
    DISPLAYCONFIG_MODE_INFO modes[max_modes]{};
    UINT32 paths_count = 0, modes_count = 0;
    bool obtained = false;
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        LONG code = GetDisplayConfigBufferSizes(flags, &paths_count, &modes_count);
        if (code != ERROR_SUCCESS) { unavailable(flags, error_code(code)); return; }
        if (paths_count == 0 || paths_count > max_paths || modes_count == 0 || modes_count > max_modes) {
            unavailable(flags, "WINDOWS_DISPLAY_COUNT_LIMIT"); return;
        }
        const UINT32 path_capacity = paths_count, mode_capacity = modes_count;
        code = QueryDisplayConfig(flags, &paths_count, paths, &modes_count, modes, nullptr);
        if (code == ERROR_INSUFFICIENT_BUFFER) continue;
        if (code != ERROR_SUCCESS) { unavailable(flags, error_code(code)); return; }
        if (paths_count == 0 || paths_count > path_capacity || modes_count == 0 || modes_count > mode_capacity) {
            unavailable(flags, "WINDOWS_DISPLAY_COUNT_LIMIT"); return;
        }
        obtained = true; break;
    }
    if (!obtained) { unavailable(flags, "WINDOWS_TOPOLOGY_CHANGED"); return; }
    std::printf("{\"status\":\"STRUCTURAL_ONLY_NOT_CAPTURE_ACCEPTANCE\",\"query_flags\":%u,"
        "\"path_count\":%u,\"mode_count\":%u,\"truncated\":false,\"paths\":[", flags, paths_count, modes_count);
    for (UINT32 i = 0; i < paths_count; ++i) {
        const auto& path = paths[i]; const auto& s = path.sourceInfo; const auto& t = path.targetInfo;
        if (i != 0) std::printf(",");
        std::printf("{\"flags\":%u,\"source_index\":%u,\"target_index\":%u,"
            "\"source_bitfield_index\":%u,\"clone_group_index\":%u,\"target_bitfield_index\":%u,\"desktop_bitfield_index\":%u,"
            "\"source_full_word_matches_endpoint\":%s,\"source_high_word_matches_endpoint\":%s,"
            "\"target_full_word_matches_endpoint\":%s,\"target_high_word_matches_endpoint\":%s}",
            path.flags, s.modeInfoIdx, t.modeInfoIdx,
            static_cast<unsigned>(s.sourceModeInfoIdx), static_cast<unsigned>(s.cloneGroupId),
            static_cast<unsigned>(t.targetModeInfoIdx), static_cast<unsigned>(t.desktopModeInfoIdx),
            truth(matches(modes, modes_count, s.modeInfoIdx, DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE, s.adapterId, s.id)),
            truth(matches(modes, modes_count, s.sourceModeInfoIdx, DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE, s.adapterId, s.id)),
            truth(matches(modes, modes_count, t.modeInfoIdx, DISPLAYCONFIG_MODE_INFO_TYPE_TARGET, t.adapterId, t.id)),
            truth(matches(modes, modes_count, t.targetModeInfoIdx, DISPLAYCONFIG_MODE_INFO_TYPE_TARGET, t.adapterId, t.id)));
    }
    std::printf("],\"mode_types\":[");
    for (UINT32 i = 0; i < modes_count; ++i) {
        if (i != 0) std::printf(",");
        std::printf("%u", static_cast<unsigned>(modes[i].infoType));
    }
    std::printf("]}");
}
int main() {
    std::printf("{\"status\":\"DIAGNOSTIC_ONLY_NOT_CAPTURE_ACCEPTANCE\",\"comparison\":\"SEPARATE_NONATOMIC_READS\",\"queries\":[");
    query(QDC_ONLY_ACTIVE_PATHS | QDC_VIRTUAL_MODE_AWARE); std::printf(","); query(QDC_ONLY_ACTIVE_PATHS);
    std::printf("],\"sdk_sizes\":{\"PathSource\":%zu,\"PathTarget\":%zu,\"DisplayPath\":%zu,\"Mode\":%zu},\"sdk_offsets\":{",
        sizeof(DISPLAYCONFIG_PATH_SOURCE_INFO), sizeof(DISPLAYCONFIG_PATH_TARGET_INFO), sizeof(DISPLAYCONFIG_PATH_INFO), sizeof(DISPLAYCONFIG_MODE_INFO));
    std::printf("\"PathSource\":{\"adapter\":%zu,\"id\":%zu,\"index\":%zu,\"status\":%zu},",
        offsetof(DISPLAYCONFIG_PATH_SOURCE_INFO, adapterId), offsetof(DISPLAYCONFIG_PATH_SOURCE_INFO, id),
        offsetof(DISPLAYCONFIG_PATH_SOURCE_INFO, modeInfoIdx), offsetof(DISPLAYCONFIG_PATH_SOURCE_INFO, statusFlags));
    std::printf("\"PathTarget\":{\"adapter\":%zu,\"id\":%zu,\"index\":%zu,\"technology\":%zu,\"rotation\":%zu,\"scaling\":%zu,\"refresh\":%zu,\"scanline\":%zu,\"available\":%zu,\"status\":%zu},",
        offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, adapterId), offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, id),
        offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, modeInfoIdx), offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, outputTechnology),
        offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, rotation), offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, scaling),
        offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, refreshRate), offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, scanLineOrdering),
        offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, targetAvailable), offsetof(DISPLAYCONFIG_PATH_TARGET_INFO, statusFlags));
    std::printf("\"DisplayPath\":{\"source\":%zu,\"target\":%zu,\"flags\":%zu},\"Mode\":{\"kind\":%zu,\"id\":%zu,\"adapter\":%zu,\"value\":%zu}},",
        offsetof(DISPLAYCONFIG_PATH_INFO, sourceInfo), offsetof(DISPLAYCONFIG_PATH_INFO, targetInfo), offsetof(DISPLAYCONFIG_PATH_INFO, flags),
        offsetof(DISPLAYCONFIG_MODE_INFO, infoType), offsetof(DISPLAYCONFIG_MODE_INFO, id),
        offsetof(DISPLAYCONFIG_MODE_INFO, adapterId), offsetof(DISPLAYCONFIG_MODE_INFO, targetMode));
    const unsigned endian = 1;
    std::printf("\"byteorder\":\"%s\"}\n", *reinterpret_cast<const unsigned char*>(&endian) == 1 ? "little" : "big");
    return 0;
}
