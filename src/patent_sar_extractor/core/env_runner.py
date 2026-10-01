"""
Environment Runner — 多 conda 环境子进程调度

统一管理各 conda 环境的 Python 路径，提供跨环境执行能力。
"""

import subprocess
import tempfile
import logging
import os
import sys
import time
import selectors
from typing import Optional

from patent_sar_extractor.paths import PACKAGE_IMPORT_ROOT, config_files

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)

_STREAM_SUPPRESS_TOKENS = (
    "Unable to register cuDNN factory",
    "Unable to register cuFFT factory",
    "Unable to register cuBLAS factory",
    "WARNING: All log messages before absl::InitializeLog()",
    "Error in PredictCost()",
    "op_level_cost_estimator.cc",
    "tensorflow/core/platform/cpu_feature_guard.cc",
    "tensorflow/core/util/port.cc",
    "tf2tensorrt/utils/py_utils.cc",
    "external/local_xla/xla/stream_executor",
    "could not open file to read NUMA node",
)


def _should_stream_child_line(line: str) -> bool:
    """Keep progress useful while suppressing TensorFlow warning floods."""
    if not line:
        return False
    return not any(token in line for token in _STREAM_SUPPRESS_TOKENS)


def _run_streamed_filtered(
    cmd: list[str],
    *,
    timeout: int,
    cwd: str,
    env: Optional[dict[str, str]],
) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_tail: list[str] = []
    deadline = time.monotonic() + timeout if timeout else None
    selector = selectors.DefaultSelector()
    if proc.stdout is not None:
        selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
            if proc.poll() is not None:
                if proc.stdout is not None:
                    rest = proc.stdout.read()
                    if rest:
                        for line in rest.splitlines(True):
                            output_tail.append(line)
                            output_tail = output_tail[-200:]
                            if _should_stream_child_line(line):
                                print(line, end="", flush=True)
                break
            events = selector.select(timeout=0.5)
            for key, _mask in events:
                line = key.fileobj.readline()
                if not line:
                    continue
                output_tail.append(line)
                output_tail = output_tail[-200:]
                if _should_stream_child_line(line):
                    print(line, end="", flush=True)
        return subprocess.CompletedProcess(cmd, proc.returncode, "".join(output_tail), "")
    finally:
        try:
            selector.close()
        except Exception:
            pass
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass

_DEFAULT_PYTHON = os.environ.get("PATENTSAR_PYTHON", sys.executable or "python3")

_ENV_OVERRIDES = {
    "base": ("PATENTSAR_BASE_PYTHON", "PATENTSAR_PYTHON"),
    "smiles_engine": ("SMILES_ENGINE_PYTHON", "PATENTSAR_SMILES_PYTHON", "PATENTSAR_PYTHON"),
    "decimer": ("DECIMER_PYTHON", "PATENTSAR_DECIMER_PYTHON"),
    "paddleocr": ("PADDLEOCR_PYTHON", "PATENTSAR_PADDLEOCR_PYTHON", "PATENTSAR_PYTHON"),
    "pymupdf": ("PYMUPDF_PYTHON", "PATENTSAR_PYMUPDF_PYTHON", "PATENTSAR_PYTHON"),
    "ocrmypdf": ("OCRMYPDF_PYTHON", "PATENTSAR_OCRMYPDF_PYTHON", "PATENTSAR_PYTHON"),
}


def _load_envs() -> dict[str, str]:
    """Load environment paths from config file."""
    config_paths = config_files("env_paths.yaml")
    if yaml is not None:
        envs: dict[str, str] = {}
        for config_path in config_paths:
            if not config_path.exists():
                continue
            with open(config_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                envs.update({str(k): str(v) for k, v in loaded.items() if v is not None})
        return envs
    envs: dict[str, str] = {}
    for config_path in config_paths:
        if not config_path.exists():
            continue
        with open(config_path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip().strip('"').strip("'")
                if key.strip() and value:
                    envs[key.strip()] = value
    return envs


def _resolve(env_name: str) -> str:
    """Resolve python path for an env, fallback to default."""
    for env_var in _ENV_OVERRIDES.get(env_name, ()):
        value = os.environ.get(env_var)
        if value and value.strip():
            return value.strip()
    envs = _load_envs()
    value = envs.get(env_name)
    if value and str(value).strip():
        return str(value).strip()
    return _DEFAULT_PYTHON


# Role identity is stable; paths are resolved from the single current configuration.
ENV_ROLES = tuple(_ENV_OVERRIDES)

ENV_REQUIRED_MODULES = {
    "base": [],
    "smiles_engine": ["cv2", "PIL", "pandas", "rdkit"],
    "decimer": ["decimer_segmentation"],
    "paddleocr": [],
    "pymupdf": ["fitz"],
    "ocrmypdf": [],
}


def get_python(env_name: str) -> str:
    """获取指定环境的 Python 路径"""
    if env_name not in ENV_ROLES:
        raise ValueError(f"Unknown conda env: {env_name}. Available: {list(ENV_ROLES)}")
    return _resolve(env_name)


def configured_model_environment() -> dict[str, str]:
    """Model paths share env_paths.local.yaml; explicit operator variables win."""
    configured = _load_envs()
    fields = {
        "PYSTOW_HOME": "decimer_models",
        "DECIMER_SEGMENTATION_MODEL_DIR": "decimer_segmentation_models",
        "PATENTSAR_ADMET_PYTHON": "admet",
        "PATENTSAR_ADMET_MODEL_DIR": "admet_models",
    }
    return {
        variable: value
        for variable, key in fields.items()
        if (value := os.environ.get(variable, "").strip() or configured.get(key, ""))
    }


def captured_runtime_environment() -> dict[str, str]:
    """Freeze interpreter/model selection at CLI start, not between its stages."""
    result = configured_model_environment()
    for role, variables in _ENV_OVERRIDES.items():
        result[variables[0]] = get_python(role)
    return result


def _execution_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build an isolated child environment without parent binary-package leakage."""

    run_env = os.environ.copy()
    run_env.pop("PYTHONPATH", None)
    for key, value in configured_model_environment().items():
        if not run_env.get(key):
            run_env[key] = value
    if extra:
        run_env.update(extra)
    return run_env


def run_in_env(
    env_name: str,
    script: str,
    args: Optional[list[str]] = None,
    timeout: int = 300,
    cwd: Optional[str] = None,
    env_extra: Optional[dict[str, str]] = None,
    stream_output: bool = False,
) -> subprocess.CompletedProcess:
    """
    在指定 conda 环境中运行 Python 脚本。

    Args:
        env_name: conda 环境名
        script: Python 脚本路径
        args: 命令行参数
        timeout: 超时秒数
        cwd: 工作目录
        env_extra: 额外环境变量 (合并到当前环境)

    Returns:
        subprocess.CompletedProcess
    """
    python = get_python(env_name)
    cmd = [python, script] + (args or [])
    logger.info(f"Running in {env_name}: {' '.join(cmd)}")

    run_env = _execution_env(env_extra)

    if stream_output:
        return _run_streamed_filtered(
            cmd,
            timeout=timeout,
            cwd=cwd or os.getcwd(),
            env=run_env,
        )

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or os.getcwd(),
        env=run_env,
    )


def run_snippet(
    env_name: str,
    code: str,
    timeout: int = 60,
    cwd: Optional[str] = None,
    env_extra: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """
    在指定 conda 环境中运行 Python 代码片段。

    将代码写入临时文件，用指定环境执行。

    Args:
        env_name: conda 环境名
        code: Python 代码
        timeout: 超时秒数
        cwd: 工作目录

    Returns:
        subprocess.CompletedProcess
    """
    python = get_python(env_name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("import runpy\n")
        f.write(f"runpy.run_path({str(PACKAGE_IMPORT_ROOT / 'patent_sar_extractor' / 'worker_bootstrap.py')!r}, run_name='__main__')\n")
        f.write(code)
        script_path = f.name

    try:
        cmd = [python, script_path]
        logger.info(f"Running snippet in {env_name} ({len(code)} chars)")

        run_env = _execution_env(env_extra)

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd(),
            env=run_env,
        )
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def check_env(env_name: str) -> dict:
    """
    检查 conda 环境是否可用。

    Returns:
        {"available": bool, "python_path": str, "version": str, "error": str|None}
    """
    python = get_python(env_name)
    result = {"available": False, "python_path": python, "version": None, "error": None}

    try:
        proc = subprocess.run(
            [python, "--version"],
            capture_output=True, text=True, timeout=10, env=_execution_env(),
        )
        if proc.returncode == 0:
            result["available"] = True
            result["version"] = proc.stdout.strip()
        else:
            result["error"] = proc.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        result["error"] = str(e)

    required_modules = ENV_REQUIRED_MODULES.get(env_name, [])
    if result["available"] and required_modules:
        code = (
            "import importlib, sys\n"
            f"mods = {required_modules!r}\n"
            "missing = []\n"
            "for mod in mods:\n"
            "    try:\n"
            "        importlib.import_module(mod)\n"
            "    except Exception as e:\n"
            "        missing.append(f'{mod}: {type(e).__name__}: {e}')\n"
            "if missing:\n"
            "    print('; '.join(missing))\n"
            "    sys.exit(1)\n"
        )
        try:
            mod_proc = subprocess.run(
                [python, "-c", code],
                capture_output=True,
                text=True,
                timeout=30,
                env=_execution_env(),
            )
            if mod_proc.returncode != 0:
                result["available"] = False
                result["error"] = f"missing modules: {mod_proc.stdout.strip() or mod_proc.stderr.strip()}"
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            result["available"] = False
            result["error"] = f"module check failed: {e}"

    return result


def check_all_envs() -> dict[str, dict]:
    """检查所有注册的 conda 环境"""
    return {name: check_env(name) for name in ENV_ROLES}
