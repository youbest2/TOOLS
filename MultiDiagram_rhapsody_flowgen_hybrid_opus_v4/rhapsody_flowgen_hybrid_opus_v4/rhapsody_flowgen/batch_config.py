# rhapsody_flowgen/batch_config.py
# Multi-diagram configuration loader (Opus v4+).
#
# Extends the single-diagram config.yaml to support MANY diagrams in one run.
# Backward compatible: if there is no `diagrams:` list, the legacy top-level
# keys (class/operation/mermaid_file) are used as a single job.
#
# YAML shape (multi):
#   project_path: "D:\\...\\FlashBootloader_SwDD.rpyx"
#   rhapsody_path: "C:\\Program Files\\IBM\\Rhapsody\\9.0.1"   # optional
#   package_path:  ["50_DetailedDesign", "50_CMP_Implementation"]  # default/base
#   diagrams:
#     - class: "ADCMonMain"
#       operation: "AdcAbs_Get_VBATT_MON"
#       mermaid_file: "flows/vbatt.mmd"
#     - class: "ADCMonMain"
#       operation: "AdcAbs_GetGroup0ConversionStatus"
#       mermaid_file: "flows/group0.mmd"
#       package_path: ["50_DetailedDesign","50_CMP_Implementation"]  # optional override
#       diagram: "AD_AdcAbs_GetGroup0ConversionStatus"               # optional AD-name override
#
# Each normalized job is a dict:
#   { class, operation, mermaid_file, package_path, diagram }
# where `diagram` defaults to "AD_<operation>".

import os
import yaml
from typing import Any, Dict, List


class ConfigError(Exception):
    pass


def _norm_pkg(pp):
    if pp is None:
        return None
    if isinstance(pp, str):
        return [pp]
    return list(pp)


def load_jobs(path: str) -> Dict[str, Any]:
    """Return {'project_path','rhapsody_path','jobs':[...]}.
    Raises ConfigError on problems."""
    if not os.path.exists(path):
        raise FileNotFoundError("Configuration file not found: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    project_path = cfg.get("project_path")
    if not project_path:
        raise ConfigError("config must define 'project_path'")
    base_pkg = _norm_pkg(cfg.get("package_path"))
    rhapsody_path = cfg.get("rhapsody_path")

    raw_diagrams = cfg.get("diagrams")
    jobs: List[Dict[str, Any]] = []

    if raw_diagrams:
        if not isinstance(raw_diagrams, list):
            raise ConfigError("'diagrams' must be a list")
        for i, d in enumerate(raw_diagrams):
            if not isinstance(d, dict):
                raise ConfigError("diagrams[%d] must be a mapping" % i)
            cls = d.get("class")
            op = d.get("operation")
            mmd = d.get("mermaid_file")
            miss = [k for k, v in (("class", cls), ("operation", op),
                                   ("mermaid_file", mmd)) if not v]
            if miss:
                raise ConfigError("diagrams[%d] missing: %s" % (i, ", ".join(miss)))
            pkg = _norm_pkg(d.get("package_path")) or base_pkg
            if not pkg:
                raise ConfigError("diagrams[%d]: no package_path (and no base package_path)" % i)
            jobs.append({
                "class": cls,
                "operation": op,
                "mermaid_file": mmd,
                "package_path": pkg,
                "diagram": d.get("diagram") or ("AD_" + str(op)),
            })
    else:
        # Legacy single-diagram fallback.
        cls = cfg.get("class"); op = cfg.get("operation"); mmd = cfg.get("mermaid_file")
        miss = [k for k, v in (("class", cls), ("operation", op),
                               ("mermaid_file", mmd)) if not v]
        if miss:
            raise ConfigError("single-diagram config missing: %s "
                              "(or provide a 'diagrams:' list)" % ", ".join(miss))
        if not base_pkg:
            raise ConfigError("config must define 'package_path'")
        jobs.append({
            "class": cls,
            "operation": op,
            "mermaid_file": mmd,
            "package_path": base_pkg,
            "diagram": cfg.get("diagram") or ("AD_" + str(op)),
        })

    return {
        "project_path": project_path,
        "rhapsody_path": rhapsody_path,
        "package_path": base_pkg,
        "jobs": jobs,
    }


def summarize(jobs_cfg: Dict[str, Any]) -> str:
    out = ["project: %s" % jobs_cfg["project_path"], "diagrams (%d):" % len(jobs_cfg["jobs"])]
    for j in jobs_cfg["jobs"]:
        out.append("  - %-40s class=%s  mmd=%s  pkg=%s"
                   % (j["diagram"], j["class"], j["mermaid_file"], "/".join(j["package_path"])))
    return "\n".join(out)
