from __future__ import annotations

import copy
import logging
from typing import Any, Protocol

from audioforge.app.application.contracts import UserNotification
from audioforge.app.utils.runtime_logging import get_runtime_log_config

logger = logging.getLogger(__name__)


class BuildExportHost(Protocol):
    window: Any
    project: Any
    exporter: Any
    validator: Any
    _active_build_scope_label: str | None
    _active_build_export_root: Any

    def _is_build_running(self) -> bool: ...

    def _current_build_request(self): ...

    def _selection_build_unavailable_message(self) -> str: ...

    def _build_scope_label(self, scope: str) -> str: ...

    def _set_build_diagnostic_summary(self, summary: str, detail: str, *, status: str = "info", metadata=None) -> None: ...

    def _publish_diagnostic_snapshot(self) -> None: ...

    def _resolve_project_relative_path(self, raw_path: str): ...

    def _format_build_plan_summary(self, plan) -> tuple[str, str]: ...

    def _format_export_diff_preview(self, export_root, plan) -> str: ...

    def _format_validation_report(self, issues) -> str: ...

    def _format_build_report(self, report_file, manifest_file) -> str: ...

    def _set_validation_diagnostic_summary(self, issues) -> None: ...

    def _start_build_worker(self, project, export_root, build_request) -> None: ...


class BuildExportController:
    def __init__(self, host: BuildExportHost) -> None:
        self._host = host

    def _append_build_log(
        self,
        message: str,
        *,
        level: str = "INFO",
        summary: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        self._host.window.append_log(
            message,
            level=level,
            subsystem="build",
            summary=summary or message,
            context=context,
        )

    def build_project(self) -> None:
        if self._host._is_build_running():
            logger.warning("Build request ignored because another build is already running.")
            self._append_build_log("构建请求已忽略：当前已有构建任务在执行。", level="WARNING", summary="构建请求已被忽略。")
            self._host.window.set_build_status(
                "构建正在进行中。",
                "请等待当前构建完成后再发起新的构建请求。",
                activate_results=True,
            )
            self._host._set_build_diagnostic_summary(
                "构建正在进行中。",
                "请等待当前构建完成后再发起新的构建请求。",
                status="warning",
            )
            self._host._publish_diagnostic_snapshot()
            return

        build_request = self._host._current_build_request()
        if build_request is None:
            message = self._host._selection_build_unavailable_message()
            self._host.window.set_build_plan_summary("选中构建未就绪。", message)
            self._host.window.set_build_status("选中构建无法开始。", message, activate_results=True)
            self._host.window.set_build_report("构建未开始\n\n原因：当前选区没有可导出的事件。\n请先选择事件或包含事件的文件夹。")
            self._host.window.show_report_tab(2)
            self._append_build_log(f"选中构建已中止：{message}", level="WARNING", summary="选中构建已中止。")
            self._host._set_build_diagnostic_summary("选中构建无法开始。", message, status="warning")
            self._host._publish_diagnostic_snapshot()
            return

        requested_scope_label = self._host._build_scope_label(build_request.scope)
        project_snapshot = copy.deepcopy(self._host.project)
        log_config = get_runtime_log_config()
        self._host.window.build_execute_button.setEnabled(False)
        self._host.window.build_button.setEnabled(False)
        self._host.window.set_build_status(
            "正在构建导出，请稍候。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 正在导出到：{self._host.project.settings.export_root}",
            activate_results=True,
        )
        self._host.window.set_build_plan_summary(
            "正在生成构建计划。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 已切换到后台构建，界面保持可响应。",
        )
        self._append_build_log(
            f"已开始构建导出：模式={requested_scope_label} 目标={build_request.selection_label}",
            summary="已开始构建导出。",
            context={"requested_scope": build_request.scope, "selection_label": build_request.selection_label, "export_root": self._host.project.settings.export_root},
        )
        self._host._set_build_diagnostic_summary(
            "正在构建导出，请稍候。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 正在导出到：{self._host.project.settings.export_root}",
            status="info",
            metadata={
                "requested_scope": build_request.scope,
                "requested_scope_label": requested_scope_label,
                "selection_label": build_request.selection_label,
                "export_root": self._host.project.settings.export_root,
            },
        )
        if log_config is not None:
            self._append_build_log(
                f"诊断日志路径：{log_config.latest_log}",
                summary="已暴露诊断日志路径。",
                context={"latest_log": str(log_config.latest_log), "fault_log": str(log_config.fault_log)},
            )
        logger.info(
            "Build requested scope=%s selection=%s export_root=%s project_name=%s",
            build_request.scope,
            build_request.selection_label,
            self._host.project.settings.export_root,
            self._host.project.name,
        )
        self._host.window.show_report_tab(2)
        self._host._publish_diagnostic_snapshot()

        export_root = self._host._resolve_project_relative_path(self._host.project.settings.export_root)
        self._host._active_build_scope_label = requested_scope_label
        self._host._active_build_export_root = export_root
        self._host._start_build_worker(project_snapshot, export_root, build_request)

    def preview_export_diff(self) -> None:
        self._host.window.clear_build_status()
        build_request = self._host._current_build_request()
        if build_request is None:
            message = self._host._selection_build_unavailable_message()
            self._host.window.set_build_plan_summary("选中构建未就绪。", message)
            self._host.window.set_build_report("构建计划不可用\n\n原因：当前选区没有可导出的事件。\n请先选择事件或包含事件的文件夹。")
            self._host.window.show_report_tab(2)
            self._append_build_log(f"选中构建预览已中止：{message}", level="WARNING", summary="构建预览已中止。")
            self._host._set_build_diagnostic_summary("构建计划不可用。", message, status="warning")
            self._host._publish_diagnostic_snapshot()
            return
        export_root = self._host._resolve_project_relative_path(self._host.project.settings.export_root)
        try:
            plan = self._host.exporter.plan_export(self._host.project, export_root, build_request)
            plan_summary, plan_detail = self._host._format_build_plan_summary(plan)
            self._host.window.set_build_plan_summary(plan_summary, plan_detail)
            self._host._set_build_diagnostic_summary(
                plan_summary,
                plan_detail,
                status="info",
                metadata={
                    "requested_scope": plan.requested_scope,
                    "requested_scope_label": self._host._build_scope_label(plan.requested_scope),
                    "effective_scope": plan.effective_scope,
                    "effective_scope_label": self._host._build_scope_label(plan.effective_scope),
                    "selection_label": plan.selection_label,
                    "rebuilt_asset_count": len(plan.rebuilt_asset_keys),
                    "reused_asset_count": len(plan.reused_asset_keys),
                    "removed_asset_count": len(plan.removed_asset_keys),
                    "out_of_scope_dirty_count": len(plan.out_of_scope_dirty_asset_keys),
                    "export_root": str(export_root),
                },
            )
            report = self._host._format_export_diff_preview(export_root, plan)
        except Exception as exc:
            self._host.window.set_build_plan_summary("构建计划生成失败。", str(exc))
            self._host._set_build_diagnostic_summary("构建计划生成失败。", str(exc), status="error")
            report = f"导出差异预览失败\n\n导出目录：{export_root}\n原因：{exc}"
            self._append_build_log(
                f"导出差异预览失败：{exc}",
                level="ERROR",
                summary="导出差异预览失败。",
                context={"export_root": str(export_root)},
            )
        self._host.window.set_build_report(report)
        self._host.window.show_report_tab(2)
        self._append_build_log("已生成导出差异预览。", summary="已生成导出差异预览。", context={"export_root": str(export_root)})
        self._host._publish_diagnostic_snapshot()

    def handle_build_validation_blocked(self, issues, error_count: int) -> None:
        requested_scope_label = self._host._active_build_scope_label or "当前构建"
        logger.info("Build blocked by validation scope=%s errors=%d", requested_scope_label, error_count)
        self._host.window.set_validation_report(self._host._format_validation_report(issues), issues)
        self._append_build_log(
            f"构建已中止，存在 {error_count} 个错误。",
            level="ERROR",
            summary="构建被校验拦截。",
            context={"error_count": error_count, "requested_scope_label": requested_scope_label},
        )
        self._host.window.set_build_plan_summary("构建已中止。", f"{requested_scope_label} 在校验阶段被拦截：存在 {error_count} 个错误。")
        self._host.window.set_build_status("构建已中止。", f"校验阶段发现 {error_count} 个错误，请先在校验修复页处理后再重新构建。")
        self._host.window.show_report_tab(1)
        self._host.window.show_validation_summary(issues)
        self._host._set_validation_diagnostic_summary(issues)
        self._host._set_build_diagnostic_summary(
            "构建已中止。",
            f"{requested_scope_label} 在校验阶段被拦截：存在 {error_count} 个错误。",
            status="error",
            metadata={
                "error_count": error_count,
                "requested_scope_label": requested_scope_label,
                "export_root": str(self._host._active_build_export_root or self._host.project.settings.export_root),
            },
        )
        self._host._publish_diagnostic_snapshot()

    def handle_build_failure(self, error_message: str, plan) -> None:
        requested_scope_label = self._host._active_build_scope_label or "当前构建"
        export_root = self._host._active_build_export_root or self._host._resolve_project_relative_path(self._host.project.settings.export_root)
        logger.error("Build failed scope=%s export_root=%s error=%s", requested_scope_label, export_root, error_message)
        failure_message = f"构建失败：{error_message}"
        self._append_build_log(
            failure_message,
            level="ERROR",
            summary="构建失败。",
            context={"requested_scope_label": requested_scope_label, "export_root": str(export_root)},
        )
        self._host.window.set_build_status(
            "构建失败。",
            f"模式：{requested_scope_label} | 导出目录：{export_root} | 原因：{error_message}",
            activate_results=True,
        )
        if plan is not None:
            plan_summary, plan_detail = self._host._format_build_plan_summary(plan)
            self._host.window.set_build_plan_summary(plan_summary, plan_detail)
        self._host.window.set_build_report(
            "\n".join([
                "构建失败",
                "",
                f"工程：{self._host.project.name}",
                f"请求范围：{requested_scope_label}",
                f"导出目录：{export_root}",
                f"原因：{error_message}",
            ])
        )
        self._host.window.show_report_tab(2)
        self._host._set_build_diagnostic_summary(
            "构建失败。",
            f"模式：{requested_scope_label} | 导出目录：{export_root} | 原因：{error_message}",
            status="error",
            metadata={
                "requested_scope_label": requested_scope_label,
                "export_root": str(export_root),
                "selection_label": self._host._active_build_scope_label or requested_scope_label,
            },
        )
        self._host._publish_diagnostic_snapshot()
        self._host.window.present_notification(UserNotification(level="error", title="构建失败", message=error_message))

    def handle_build_success(self, result, issues) -> None:
        logger.info(
            "Build succeeded export_root=%s report_file=%s rebuilt_assets=%d reused_assets=%d",
            result.export_root,
            result.report_file,
            len(result.plan.rebuilt_asset_keys),
            len(result.plan.reused_asset_keys),
        )
        requested_scope_label = self._host._active_build_scope_label or self._host._build_scope_label(result.plan.requested_scope)
        build_report = self._host._format_build_report(result.report_file, result.manifest_file)
        self._host.window.set_validation_report(self._host._format_validation_report(issues), issues)
        self._append_build_log(
            f"构建完成：{result.data_file}",
            summary="构建完成。",
            context={"data_file": str(result.data_file), "manifest_file": str(result.manifest_file), "export_root": str(result.export_root)},
        )
        self._append_build_log(
            f"已生成清单：{result.manifest_file}",
            summary="已生成构建清单。",
            context={"manifest_file": str(result.manifest_file)},
        )
        effective_scope_label = self._host._build_scope_label(result.plan.effective_scope)
        scope_display = requested_scope_label if effective_scope_label == requested_scope_label else f"{requested_scope_label} -> {effective_scope_label}"
        plan_summary, plan_detail = self._host._format_build_plan_summary(result.plan)
        self._host.window.set_build_plan_summary(plan_summary, plan_detail)
        self._host.window.set_build_status(
            "构建完成。",
            f"模式：{scope_display} | 已导出到：{result.data_file} | 清单：{result.manifest_file}",
            activate_results=True,
        )
        self._host.window.set_build_report(build_report)
        self._host.window.show_report_tab(2)
        self._host._set_validation_diagnostic_summary(issues)
        self._host._set_build_diagnostic_summary(
            "构建完成。",
            f"模式：{scope_display} | 已导出到：{result.data_file} | 清单：{result.manifest_file}",
            status="success",
            metadata={
                "requested_scope": result.plan.requested_scope,
                "requested_scope_label": requested_scope_label,
                "effective_scope": result.plan.effective_scope,
                "effective_scope_label": effective_scope_label,
                "selection_label": result.plan.selection_label,
                "rebuilt_asset_count": len(result.plan.rebuilt_asset_keys),
                "reused_asset_count": len(result.plan.reused_asset_keys),
                "removed_asset_count": len(result.plan.removed_asset_keys),
                "out_of_scope_dirty_count": len(result.plan.out_of_scope_dirty_asset_keys),
                "export_root": str(result.export_root),
                "data_file": str(result.data_file),
                "manifest_file": str(result.manifest_file),
            },
        )
        self._host._publish_diagnostic_snapshot()

    def finalize_build_worker(self) -> None:
        logger.info("Build worker cleanup finished.")
        self._host.window.build_execute_button.setEnabled(True)
        self._host.window.build_button.setEnabled(True)
        self._host._build_thread = None
        self._host._build_worker = None
        self._host._active_build_scope_label = None
        self._host._active_build_export_root = None