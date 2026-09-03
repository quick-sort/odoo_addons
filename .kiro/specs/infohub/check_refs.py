"""静态交叉校验：视图/ACL 引用的模型与字段是否真实存在。

无法启动 Odoo 时，这能提前抓出绝大多数"安装时才炸"的错误：
拼错的字段名、忘记定义的字段、ACL 里写错的模型名。
"""

import ast
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

WORKSPACE = pathlib.Path("/Users/rui/workspace/odoo-projects/odoo_addons")
# 默认检查全部 infohub* 模块；也可用命令行参数指定
MODULES = sys.argv[1:] or sorted(p.name for p in WORKSPACE.glob("infohub*") if p.is_dir())
ROOT = None  # 由 main() 逐个模块设置

RELATIONAL = {"Many2one", "One2many", "Many2many"}

# Odoo 自动提供的字段 + mail.thread / collection.base 带来的字段
IMPLICIT = {
    "id", "display_name", "create_date", "create_uid", "write_date", "write_uid",
    "__last_update", "message_ids", "message_follower_ids", "message_partner_ids",
    "message_is_follower", "message_unread", "message_unread_counter",
    "message_needaction", "message_needaction_counter", "message_has_error",
    "message_has_error_counter", "message_attachment_count", "website_message_ids",
    "message_has_sms_error", "message_main_attachment_id", "rating_ids",
    "email_cc", "activity_ids",
}


def collect_models(roots):
    """从 AST 收集 model -> {field: comodel}，以及 _inherit 关系。

    必须跟随 _inherit 链：字段可能来自抽象基类（例如 infohub.paper 的 item_id 来自
    infohub.medium.payload）。不跟随会产生"字段不存在"的假阳性。
    """
    models = {}
    parents_of = {}
    for root in roots:
        for path in sorted((root / "models").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                name = None
                parents = []
                fields = {}
                for stmt in node.body:
                    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                        continue
                    target = stmt.targets[0]
                    if not isinstance(target, ast.Name):
                        continue
                    key = target.id
                    if key == "_name" and isinstance(stmt.value, ast.Constant):
                        name = stmt.value.value
                    elif key == "_inherit":
                        if isinstance(stmt.value, ast.Constant):
                            parents = [stmt.value.value]
                        elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                            parents = [
                                e.value for e in stmt.value.elts
                                if isinstance(e, ast.Constant)
                            ]
                    elif isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        if (
                            isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "fields"
                        ):
                            comodel = None
                            if func.attr in RELATIONAL:
                                if stmt.value.args and isinstance(
                                    stmt.value.args[0], ast.Constant
                                ):
                                    comodel = stmt.value.args[0].value
                                for kw in stmt.value.keywords:
                                    if kw.arg == "comodel_name" and isinstance(
                                        kw.value, ast.Constant
                                    ):
                                        comodel = kw.value.value
                            fields[key] = comodel
                model_name = name or (parents[0] if parents else None)
                if not model_name:
                    continue
                models.setdefault(model_name, {}).update(fields)
                if name and parents:
                    # 只有"新建模型 + 继承基类"才是真的父子关系；
                    # _inherit 且无 _name 是扩展自身，不算父类
                    parents_of.setdefault(model_name, []).extend(
                        p for p in parents if p != model_name
                    )
    return models, parents_of


def fields_for(models, model, parents_of=None, seen=None):
    """模型的全部字段名，含从 _inherit 基类继承来的。"""
    parents_of = parents_of or {}
    seen = seen or set()
    if model in seen:
        return set()
    seen.add(model)
    known = set(models.get(model, {})) | IMPLICIT
    for parent in parents_of.get(model, []):
        known |= fields_for(models, parent, parents_of, seen)
    return known


def check_views(models, parents_of, root):
    errors = []
    for path in sorted((root / "views").glob("*.xml")):
        tree = ET.parse(path)
        for record in tree.iter("record"):
            if record.get("model") != "ir.ui.view":
                continue
            model_name = None
            arch = None
            for child in record:
                if child.get("name") == "model":
                    model_name = (child.text or "").strip()
                elif child.get("name") == "arch":
                    arch = child
            if not model_name or arch is None:
                continue
            if model_name not in models:
                errors.append(f"{path.name}: 未知模型 {model_name}")
                continue
            _walk(arch, model_name, models, parents_of, path, errors)
    return errors


def _walk(node, model_name, models, parents_of, path, errors):
    known = fields_for(models, model_name, parents_of)
    for child in list(node):
        if child.tag == "field":
            fname = child.get("name")
            if not fname:
                continue
            if fname not in known:
                errors.append(
                    f"{path.name}: 模型 {model_name} 上不存在字段 '{fname}'"
                )
                continue
            # 嵌套子视图：内部字段属于共同模型
            comodel = models.get(model_name, {}).get(fname)
            if len(child) and comodel:
                for sub in child:
                    _walk(sub, comodel, models, parents_of, path, errors)
            elif len(child):
                for sub in child:
                    _walk(sub, model_name, models, parents_of, path, errors)
        else:
            _walk(child, model_name, models, parents_of, path, errors)


def check_acl(models, root):
    errors = []
    csv_path = root / "security" / "ir.model.access.csv"
    if not csv_path.exists():
        return errors
    for line in csv_path.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        model_ref = parts[2]
        model_name = model_ref.replace("model_", "", 1).replace("_", ".")
        if model_name not in models:
            errors.append(f"ir.model.access.csv: 未知模型 {model_ref} -> {model_name}")
    return errors


def check_domain_fields(models, parents_of, root):
    """检查记录规则里引用的字段。"""
    errors = []
    for rule_path in sorted((root / "security").glob("*.xml")):
        tree = ET.parse(rule_path)
        for record in tree.iter("record"):
            if record.get("model") != "ir.rule":
                continue
            model_name = None
            domain = None
            for child in record:
                if child.get("name") == "model_id":
                    ref = child.get("ref") or ""
                    model_name = ref.replace("model_", "", 1).replace("_", ".")
                elif child.get("name") == "domain_force":
                    domain = (child.text or "").strip()
            if not model_name or not domain:
                continue
            if model_name not in models:
                errors.append(f"{rule_path.name}: 未知模型 {model_name}")
                continue
            known = fields_for(models, model_name, parents_of)
            for fname in re.findall(r"\('([a-z_0-9]+)'\s*,", domain):
                if fname not in known:
                    errors.append(
                        f"{rule_path.name}: 规则 domain 引用了 {model_name} 上"
                        f"不存在的字段 '{fname}'"
                    )
    return errors


def check_data_fields(models, parents_of, root):
    """检查 data/ 里数据记录引用的字段。"""
    errors = []
    for path in sorted((root / "data").glob("*.xml")):
        tree = ET.parse(path)
        for record in tree.iter("record"):
            model_name = record.get("model")
            if not model_name or model_name not in models:
                continue  # 非 infohub 模型（ir.cron 等）跳过
            known = fields_for(models, model_name, parents_of)
            for child in record:
                if child.tag != "field":
                    continue
                fname = child.get("name")
                if fname and fname not in known:
                    errors.append(
                        f"{path.name}: {model_name} 上不存在字段 '{fname}'"
                    )
    return errors


def main():
    roots = [WORKSPACE / name for name in MODULES]
    missing = [r for r in roots if not r.exists()]
    if missing:
        print(f"模块不存在: {[str(m) for m in missing]}")
        return 1

    # 模型定义跨模块合并（卫星模块会用 _inherit 扩展核心模型）
    models, parents_of = collect_models(roots)
    print(f"模块 {MODULES}")
    print(f"合并后 {len(models)} 个模型\n")

    errors = []
    for root in roots:
        errors += check_views(models, parents_of, root)
        errors += check_acl(models, root)
        errors += check_domain_fields(models, parents_of, root)
        errors += check_data_fields(models, parents_of, root)

    if errors:
        print(f"发现 {len(errors)} 个问题：")
        for err in errors:
            print(f"  ✗ {err}")
        return 1
    print("✓ 视图、ACL、记录规则、数据文件的模型与字段引用全部有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
