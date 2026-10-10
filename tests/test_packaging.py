"""O layout do modelo registrado (`code_paths`) precisa achar prompts e config."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_code_paths_layout_resolves_prompts_and_config(tmp_path):
    code = tmp_path / "code"  # como o MLflow copia: code/{legal_agent,config,prompts}
    shutil.copytree(ROOT / "src" / "legal_agent", code / "legal_agent")
    shutil.copytree(ROOT / "config", code / "config")
    shutil.copytree(ROOT / "prompts", code / "prompts")

    probe = (
        "from legal_agent.config import PROJECT_ROOT, load_config;"
        "from legal_agent import agent;"
        "print(PROJECT_ROOT); print(agent._prompt('system_pt_br.txt')[:10]); print(load_config().k)"
    )
    out = subprocess.run([sys.executable, "-c", probe], cwd=code, capture_output=True, text=True,
                         encoding="utf-8", check=True,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"}).stdout.splitlines()
    assert Path(out[0]) == code
    assert out[1]
    assert out[2] == "5"
