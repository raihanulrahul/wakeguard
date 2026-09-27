# Keep WakeGuard separate from existing Python projects

Use `Setup-WakeGuard-Private.ps1` instead of installing/reinstalling a system Python.

```powershell
cd D:\Codes\wakeguard
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-WakeGuard-Private.ps1
```

After the setup succeeds, launch `Start-WakeGuard.cmd`. No activation is required.

## Scope

The script downloads a pinned, SHA-256-verified portable uv executable from Astral's release and uses its `python install` with `--no-bin`, `--no-registry`, `--no-config`, and a repository-local runtime/cache directory. It does NOT use Astral's global installation script. The private CPython runtime is a build from Astral's python-build-standalone project, not a Windows-installed Python.org distribution. The Python version is 3.12.10 x64 to retain the application's tested version.

- `.runtime/`: private interpreter, invoked by its absolute path.
- `.bootstrap/`: download helper, caches/temp files and before/after safety snapshots.
- `.venv_wakeguard/`, `.venv_phone/`: application package environments.
- Ordinary app data still lives in `%LOCALAPPDATA%\WakeGuard`.

No existing Python interpreter is uninstalled or upgraded. No PATH/PATHEXT change, Python launcher installation, .py file association change, Windows Python registration, global pip operation or unrelated process termination is requested. Environment variable overrides affect only setup and are restored on exit. The script refuses junction paths and existing application environments that use a different base interpreter. It never auto-deletes an old environment.

Inherited pip target/prefix/user settings are cleared for setup and pip configuration files disabled, so another project's configuration cannot redirect these installs. A before/after snapshot compares command resolution, PATH/PATHEXT, Python registrations and the inspected .py/.pyw associations. Unexpected differences cause a visible error, not an automatic rollback. This is a meaningful isolation check, not a guarantee about every possible third-party program or a security sandbox. Downloads still use disk/network and installed binaries are trusted software.

Existing Python 3.10/3.11/3.14, their packages and VS Code interpreter selections can remain as they are. In a WakeGuard workspace select `.venv_wakeguard\Scripts\python.exe` only; do not change a global VS Code default. Keep the private runtime directory: the project's virtual environments depend on it. Recreate the setup on each PC rather than copying environments.

Repeat this private setup for future dependency updates. The original `Setup-WakeGuard.ps1` does not automatically discover `.runtime`; the private wrapper supplies the explicit interpreter path.

## Validation

See the **Private runtime isolation check** Actions workflow. It runs the whole private setup on Windows PowerShell, verifies preservation of the existing default Python and an unrelated environment, exercises an inherited PIP_TARGET isolation check, runs the GUI regression suite, and retries setup for safe reuse. This does not exercise the user's physical camera, actual sound output or Apple credentials.

Primary references:
- https://docs.astral.sh/uv/reference/cli/#uv-python-install
- https://docs.astral.sh/uv/concepts/python-versions/
- https://docs.python.org/3.12/library/venv.html
- https://pip.pypa.io/en/stable/topics/configuration/
