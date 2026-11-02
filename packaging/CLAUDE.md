# seeker — packaging rules

Standing facts for packaging, the frozen app and its updates, moved here
from the root `CLAUDE.md` so it stays short. Same rules as the root:
present tense, each fact linked to the HISTORY entry holding its
investigation; `docs/history/README.md` resolves any `§N`.

## Packaging

- `sys.frozen` gates every bundled-resource lookup through
  `sys._MEIPASS`. One-folder mode, deliberately: numba's JIT cache
  persists only there (~1 s against ~18–21 s a run).
  [§30](../docs/history/025-031.md#30)
- **The bundle carries every runtime distribution's licence texts**
  (`licenses/<name>/`); a wheel with none gets a vendored text in
  `packaging/licenses/` (`bundle_info.VENDORED_LICENSES`), never
  edited, and `license_datas()` fails the build otherwise.
  [§215](../docs/history/211-240.md#215)
- PyInstaller ad-hoc-signs with no `codesign_identity`: say "ad-hoc
  signed, not notarized", never "unsigned".
  [§36](../docs/history/032-046.md#36)
- `packaging/build_dmg.py` writes the gitignored
  `_build_info_generated.py`; the tracked `_build_info.py` only
  imports it (fallback `"dev"`). Never write the tracked file.
  [§83](../docs/history/072-107.md#83)
- **Seeker asks GitHub for a release only from Help, or at startup
  when Settings → General → Updates is on** (`ui/update_scheduler.py`):
  at most once in 24 hours (`is_due`), stamped before the request.
  Only `UPDATE_AVAILABLE` reaches the user (one tray notice and a Help
  entry); `check_for_update()` never raises.
  [§209](../docs/history/181-210.md#209)
- A GUI launch gets launchd's minimal PATH:
  `docker_setup.ensure_full_path_environment()` merges `path_helper`
  and Homebrew/Docker Desktop fallbacks once, in
  `Application.__init__`. [§44](../docs/history/032-046.md#44)
- `login_item.py` (`SMAppService`) is a no-op outside a frozen `.app`
  (no bundle identifier); its status is read live, never stored.
  Register/unregister on a packaged build is UNVERIFIED.
  [§131](../docs/history/121-150.md#131)
- **Architecture text has one source:**
  `cpu_architecture.describe_architecture()`. Under Rosetta an x86_64
  process reports `platform.machine()` x86_64 and
  `sysctl.proc_translated` 1; natively 0 (ctypes `sysctlbyname`,
  observed 2026-11-02; a real Intel Mac UNVERIFIED).
  [§250](../docs/history/241-270.md#250)
