from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import (
    Download,
    Locator,
    Page,
    Response,
    TimeoutError as PlaywrightTimeoutError,
)

from ehrm.browser.download import DownloadManager
from ehrm.core.exceptions import (
    DownloadTimeoutError,
    EmployeeNotFoundError,
    MultipleEmployeeMatchedError,
    QueryResultTimeoutError,
    TaskCancelledError,
    WebsiteStructureChangedError,
)
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.excel_models import EmployeeRecord, WorkGroup


_MONTH_NAMES = {
    1: "一月",
    2: "二月",
    3: "三月",
    4: "四月",
    5: "五月",
    6: "六月",
    7: "七月",
    8: "八月",
    9: "九月",
    10: "十月",
    11: "十一月",
    12: "十二月",
}
_INSURANCE_DISPLAY = {
    "养老保险": "养老",
    "工伤保险": "工伤",
    "失业保险": "失业",
    "医疗保险": "医疗",
    "生育保险": "生育",
}
_LOGGER = logging.getLogger("ehrm")


class RightsStatementPage:
    """All site-specific interaction is intentionally kept in this page object."""

    def __init__(
        self,
        page: Page,
        settings: AppSettings,
        downloads: DownloadManager,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        self.selectors = settings.rights_statement
        self.downloads = downloads
        self.cancel_check = cancel_check
        self._current_insurance: str | None = None
        self._current_start_month: str | None = None
        self._current_end_month: str | None = None
        self._prepared_person_key: tuple[str, str] | None = None

    def open(self, *, reset: bool = False) -> None:
        self._raise_if_cancelled()
        start_selector = self.selectors.start_month
        if start_selector and self._visible(self.page.locator(start_selector)):
            if not reset:
                # Keep using this exact tab. The target site binds authentication
                # to the tab, and retaining the form also lets us reuse filters.
                return
            self.page.reload(wait_until="domcontentloaded")
            self._invalidate_filter_cache()
            self.page.locator(start_selector).wait_for(state="visible")
            return

        self._invalidate_filter_cache()
        if self.settings.site.rights_statement_url:
            self.page.goto(
                self.settings.site.rights_statement_url, wait_until="domcontentloaded"
            )
        else:
            navigation = self.settings.navigation
            self._click_if_visible(navigation.province_entry)
            self._click_if_visible(navigation.city_entry)
            menu = self._required(
                navigation.rights_statement_menu, "rights_statement_menu"
            )
            self.page.locator(menu).last.click()

        self.page.locator(
            self._required(self.selectors.start_month, "start_month")
        ).wait_for(state="visible")

    def prepare_group(self, group: WorkGroup) -> None:
        self._raise_if_cancelled()
        first = group.first
        # Fill the most specific person condition first. Insurance and month
        # controls are handled afterwards so the page sees the intended query
        # order before the query button is clicked.
        self._fill_person_query(first)
        self._prepared_person_key = self._person_query_key(first)
        _LOGGER.info(
            "已优先填写人员查询条件 类型=%s",
            "社会保障号码" if first.identity_number else "姓名",
        )
        actual_insurance = self._read_insurance()
        actual_start = self._read_month(self.selectors.start_month)
        actual_end = self._read_month(self.selectors.end_month)
        _LOGGER.info(
            "筛选条件 页面实际值=[险种:%s, 开始:%s, 结束:%s] "
            "Excel目标值=[险种:%s, 开始:%s, 结束:%s]",
            actual_insurance or "未读取到",
            actual_start or "未读取到",
            actual_end or "未读取到",
            first.insurance_type,
            first.start_month,
            first.end_month,
        )
        if not self._insurance_matches(first.insurance_type):
            self._select_insurance(first.insurance_type)
            _LOGGER.info("已重新选择险种=%s", first.insurance_type)
        else:
            _LOGGER.info("页面险种与目标一致，保持当前选择")
        self._current_insurance = first.insurance_type
        self._raise_if_cancelled()
        if not self._month_matches(self.selectors.start_month, first.start_month):
            self._set_month(self.selectors.start_month, first.start_month)
            _LOGGER.info("已重新选择开始年月=%s", first.start_month)
        else:
            _LOGGER.info("页面开始年月与目标一致，保持当前选择")
        self._current_start_month = first.start_month
        self._raise_if_cancelled()
        if not self._month_matches(self.selectors.end_month, first.end_month):
            self._set_month(self.selectors.end_month, first.end_month)
            _LOGGER.info("已重新选择结束年月=%s", first.end_month)
        else:
            _LOGGER.info("页面结束年月与目标一致，保持当前选择")
        self._current_end_month = first.end_month

        if not (
            self._insurance_matches(first.insurance_type)
            and self._month_matches(self.selectors.start_month, first.start_month)
            and self._month_matches(self.selectors.end_month, first.end_month)
        ):
            raise WebsiteStructureChangedError(
                "险种或起止年月未在页面中生效",
                details=(
                    f"页面实际值：险种={self._read_insurance() or '未读取到'}，"
                    f"开始={self._read_month(self.selectors.start_month) or '未读取到'}，"
                    f"结束={self._read_month(self.selectors.end_month) or '未读取到'}"
                ),
            )
        _LOGGER.info(
            "筛选条件最终校验通过 页面实际值=[险种:%s, 开始:%s, 结束:%s]",
            self._read_insurance(),
            self._read_month(self.selectors.start_month),
            self._read_month(self.selectors.end_month),
        )

    def _read_month(self, selector: str) -> str | None:
        try:
            return self.page.locator(
                self._required(selector, "month input")
            ).input_value().strip()
        except (PlaywrightError, AttributeError):
            return None

    def _month_matches(self, selector: str, expected: str) -> bool:
        return self._read_month(selector) == expected

    def _read_insurance(self) -> str | None:
        try:
            locator = self.page.locator(
                self._required(self.selectors.insurance_type, "insurance_type")
            ).first
            actual = locator.evaluate(
                """element => {
                    if (element.tagName === 'SELECT') {
                        return element.selectedOptions[0]?.textContent || element.value;
                    }
                    const root = element.closest('.ant-select') || element;
                    const selected = root.querySelector(
                        '.ant-select-selection-selected-value, .ant-select-selection-item'
                    );
                    return selected?.textContent || element.value || root.textContent;
                }"""
            )
            return re.sub(r"\s+", "", str(actual)) or None
        except (PlaywrightError, AttributeError):
            return None

    def _insurance_matches(self, insurance_type: str) -> bool:
        expected = _INSURANCE_DISPLAY.get(
            insurance_type,
            insurance_type.removesuffix("保险"),
        )
        actual = self._read_insurance()
        return actual is not None and expected in actual

    def query_and_add(self, record: EmployeeRecord) -> None:
        query_button = self._required(self.selectors.query_button, "query_button")
        try:
            self._raise_if_cancelled()
            record_key = self._person_query_key(record)
            if self._prepared_person_key != record_key:
                self._fill_person_query(record)
            else:
                _LOGGER.info("复用已优先填写的人员查询条件 row=%s", record.row_number)
            self._prepared_person_key = None
            self._pause()
            self.page.locator(query_button).click()
            # A query can briefly expose an old result table below the loading
            # mask. Never inspect rows until every visible mask has disappeared
            # and the page has remained stable for consecutive samples.
            self._wait_for_loading_to_finish(
                self.selectors.query_result_timeout_ms
            )
            row = self._wait_for_employee_row(record)
            self._check_row(row)
            self._pause()
            self._raise_if_cancelled()
            self.page.locator(
                self._required(self.selectors.transfer_left, "transfer_left")
            ).click()
            self._wait_until_transferred(record)
            self._raise_if_cancelled()
        except (
            EmployeeNotFoundError,
            MultipleEmployeeMatchedError,
            QueryResultTimeoutError,
        ):
            raise
        except PlaywrightTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "查询或添加人员超时，页面结构可能已经变化", details=str(exc)
            ) from exc
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                "无法完成查询和人员选择", details=str(exc)
            ) from exc

    def _fill_person_query(self, record: EmployeeRecord) -> None:
        """Uses social-security number first; name remains a defensive fallback."""
        employee_selector = self._required(
            self.selectors.employee_name, "employee_name"
        )
        employee = self.page.locator(employee_selector)
        if record.identity_number:
            social_selector = self._required(
                self.selectors.social_security_number,
                "social_security_number",
            )
            social = self.page.locator(social_selector)
            social.fill(record.identity_number)
            employee.fill("")
            return

        # Excel imports reject blank identity numbers. This fallback supports
        # future callers without weakening the Excel validation contract.
        if self.selectors.social_security_number:
            self.page.locator(self.selectors.social_security_number).fill("")
        employee.fill(record.name)

    @staticmethod
    def _person_query_key(record: EmployeeRecord) -> tuple[str, str]:
        if record.identity_number:
            return "identity", record.identity_number.strip().upper()
        return "name", record.name.strip()

    def download_selected(
        self,
        output_dir: Path,
        fallback_filename: str,
        records: list[EmployeeRecord] | tuple[EmployeeRecord, ...],
    ) -> Path:
        try:
            self._raise_if_cancelled()
            self._select_current_group(records)
            self._pause()
            self.page.locator(
                self._required(self.selectors.generate_button, "generate_button")
            ).click()

            dialog = self.page.locator(
                self._required(self.selectors.preview_dialog, "preview_dialog")
            ).last
            dialog.wait_for(state="visible")
            _LOGGER.info("权益单预览弹窗已显示")
            if self.selectors.download_ready:
                # A reused workbench page can retain hidden print-layout clones.
                # Waiting for `.last` may therefore target an invisible old node.
                self._wait_for_preview_ready(
                    dialog,
                    self.selectors.download_ready,
                    self.selectors.preview_ready_timeout_ms,
                )
            _LOGGER.info("权益单正文已加载")
            self.page.wait_for_timeout(
                max(0, self.selectors.preview_download_delay_ms)
            )

            download_button = dialog.get_by_role(
                "button", name=re.compile(r"下载$")
            ).first
            if download_button.count() == 0:
                download_button = dialog.locator(
                    self._required(self.selectors.download_button, "download_button")
                ).first
            download_button.wait_for(state="visible")
            self._raise_if_cancelled()
            _LOGGER.info("开始触发权益单下载")
            path = self._download_with_fallbacks(
                download_button,
                output_dir,
                fallback_filename,
            )
            _LOGGER.info("PDF 已保存并通过完整性校验 size=%s", path.stat().st_size)

            self._dismiss_preview(dialog)
            return path
        except PlaywrightTimeoutError as exc:
            raise DownloadTimeoutError(
                "等待权益单预览或下载超时",
                details="请确认预览窗口中的下载按钮定位器",
            ) from exc
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                "无法预览或下载权益单", details=str(exc)
            ) from exc

    def _download_with_fallbacks(
        self,
        button: Locator,
        output_dir: Path,
        fallback_filename: str,
    ) -> Path:
        """Captures standard, CDP-managed, or response-backed PDF downloads."""
        captured_downloads: list[Download] = []
        candidate_responses: list[Response] = []

        def on_download(download: Download) -> None:
            captured_downloads.append(download)

        def on_response(response: Response) -> None:
            headers = response.headers
            content_type = headers.get("content-type", "").lower()
            disposition = headers.get("content-disposition", "").lower()
            if (
                "application/pdf" in content_type
                or "application/octet-stream" in content_type
                or "attachment" in disposition
                or ".pdf" in disposition
            ):
                candidate_responses.append(response)

        self.page.on("download", on_download)
        self.page.on("response", on_response)

        total_timeout = max(1_000, self.selectors.download_timeout_ms)
        retry_at = time.monotonic() + min(5_000, total_timeout) / 1000
        deadline = time.monotonic() + total_timeout / 1000
        retried = False

        try:
            try:
                # Do not let Playwright wait indefinitely for a navigation
                # that this site's custom download handler never completes.
                button.click(timeout=5_000, no_wait_after=True)
            except PlaywrightTimeoutError:
                if not captured_downloads:
                    _LOGGER.info("下载按钮常规点击被阻塞，改用 DOM 点击")
                    button.evaluate("element => element.click()")
            while time.monotonic() < deadline:
                if captured_downloads:
                    _LOGGER.info("下载捕获方式=playwright_download_event")
                    return self.downloads.save(
                        captured_downloads.pop(0),
                        output_dir,
                        fallback_filename,
                    )

                response_pdf = self._response_pdf(candidate_responses)
                if response_pdf is not None:
                    _LOGGER.info("下载捕获方式=pdf_network_response")
                    return self.downloads.save_bytes(
                        response_pdf,
                        output_dir,
                        fallback_filename,
                    )

                self._raise_if_cancelled()

                if not retried and time.monotonic() >= retry_at:
                    _LOGGER.info("首次下载点击未产生文件，等待后重试")
                    self.page.wait_for_timeout(
                        max(1_000, self.selectors.preview_download_delay_ms)
                    )
                    button.evaluate("element => element.click()")
                    retried = True
                self.page.wait_for_timeout(200)
        finally:
            self.page.remove_listener("download", on_download)
            self.page.remove_listener("response", on_response)

        raise PlaywrightTimeoutError(
            "点击下载后未捕获下载事件、PDF 响应或临时文件"
        )

    def _wait_for_preview_ready(
        self,
        dialog: Locator,
        selector: str,
        timeout_ms: int,
    ) -> None:
        # Preview content may live inside an iframe or be painted to canvas. Do
        # not poll with screenshots here: repeatedly disabling animations while
        # taking screenshots makes the modal visibly flash on some browsers.
        marker_timeout_ms = min(max(1_000, timeout_ms), 10_000)
        deadline = time.monotonic() + marker_timeout_ms / 1000
        started = time.monotonic()
        previous_signature: str | None = None
        stable_samples = 0
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            for frame in self.page.frames:
                try:
                    locator = frame.locator(selector)
                    if any(
                        self._visible(locator.nth(index))
                        for index in range(locator.count())
                    ):
                        _LOGGER.info("通过正文标志确认预览加载完成")
                        return
                except PlaywrightError:
                    continue

            loading = self.page.locator(self.selectors.loading_indicator).first
            if self.selectors.loading_indicator and self._visible(loading):
                previous_signature = None
                stable_samples = 0
                self.page.wait_for_timeout(200)
                continue

            # DOM/iframe/canvas geometry can be sampled without repainting or
            # altering the page. A stable structure plus the configured final
            # buffer is the fallback when the document text is inaccessible.
            if time.monotonic() - started >= 1:
                try:
                    signature = dialog.evaluate(
                        """element => {
                            const body = element.querySelector('.ant-modal-body') || element;
                            const visuals = Array.from(body.querySelectorAll(
                                'canvas, img, iframe, embed, object, svg'
                            )).map(node => {
                                const rect = node.getBoundingClientRect();
                                return [
                                    node.tagName,
                                    Math.round(rect.width),
                                    Math.round(rect.height),
                                    node.getAttribute('src') || node.getAttribute('data') || '',
                                    node.complete === undefined ? '' : node.complete
                                ];
                            });
                            return JSON.stringify({
                                htmlLength: body.innerHTML.length,
                                textLength: (body.textContent || '').length,
                                scrollWidth: body.scrollWidth,
                                scrollHeight: body.scrollHeight,
                                visuals
                            });
                        }"""
                    )
                    if signature == previous_signature:
                        stable_samples += 1
                    else:
                        stable_samples = 0
                    previous_signature = signature
                    if stable_samples >= 3:
                        _LOGGER.info("通过预览结构稳定确认加载完成")
                        return
                except PlaywrightError:
                    pass
            self.page.wait_for_timeout(250)
        _LOGGER.info(
            "预览正文不可读取且结构未稳定，达到等待上限后继续下载"
        )

    @staticmethod
    def _response_pdf(responses: list[Response]) -> bytes | None:
        while responses:
            response = responses.pop(0)
            try:
                content = response.body()
            except PlaywrightError:
                continue
            if content.startswith(b"%PDF-"):
                return content
        return None

    def clear_selected_people(self) -> None:
        """Clears the selected-side table while preserving current filters."""
        self._close_preview_if_visible()
        table = self._selected_table()
        table.wait_for(state="visible")

        if self._selected_table_is_empty(table):
            return

        self._select_all_chosen_people()
        self._pause()
        back = self._reverse_transfer_arrow()
        back.click(timeout=3_000)
        self._wait_for_loading_to_finish(
            self.selectors.transfer_result_timeout_ms
        )

        deadline = (
            time.monotonic()
            + self.selectors.transfer_result_timeout_ms / 1000
        )
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            loading = self.page.locator(self.selectors.loading_indicator).first
            if self.selectors.loading_indicator and self._visible(loading):
                self.page.wait_for_timeout(200)
                continue
            if self._selected_table_is_empty(table):
                self._pause()
                return
            self.page.wait_for_timeout(200)
        raise QueryResultTimeoutError("清空右侧已选人员列表超时")

    def _reverse_transfer_arrow(self) -> Locator:
        if self.selectors.transfer_back:
            configured = self.page.locator(self.selectors.transfer_back)
            for index in range(configured.count()):
                candidate = configured.nth(index)
                if self._visible(candidate):
                    return candidate

        left_box = self._candidate_table().bounding_box()
        right_box = self._selected_table().bounding_box()
        if left_box is None or right_box is None:
            raise WebsiteStructureChangedError("无法确定左右人员表格的位置")

        gap_left = left_box["x"] + left_box["width"]
        gap_right = right_box["x"]
        arrows: list[tuple[float, Locator]] = []
        svg_nodes = self.page.locator("svg")
        for index in range(svg_nodes.count()):
            svg = svg_nodes.nth(index)
            if not self._visible(svg):
                continue
            box = svg.bounding_box()
            if box is None:
                continue
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2
            if gap_left <= center_x <= gap_right:
                arrows.append((center_y, svg))
        if not arrows:
            raise WebsiteStructureChangedError("没有找到清空已选人员的反向箭头")
        # The screenshot/recording shows the remove (<) arrow below the add (>) arrow.
        return max(arrows, key=lambda item: item[0])[1]

    def recover_group_state(self) -> None:
        """Best-effort cleanup; reloads the same tab if the reverse arrow fails."""
        try:
            self.clear_selected_people()
            _LOGGER.info("右侧已选人员已清空")
        except TaskCancelledError:
            raise
        except Exception as exc:
            _LOGGER.info("清空已选人员失败，刷新当前页面恢复: %s", exc)
            self.open(reset=True)

    def _set_month(self, input_selector: str, value: str) -> None:
        year_text, month_text = value.split("-", maxsplit=1)
        month_name = _MONTH_NAMES[int(month_text)]
        field = self.page.locator(self._required(input_selector, "month input"))
        field.click()
        popup_selector = self._required(self.selectors.calendar_popup, "calendar_popup")
        popup = self.page.locator(popup_selector).last
        popup.wait_for(state="visible")

        year_button = popup.get_by_role(
            "button", name=re.compile(r"^\d{4}$")
        ).first
        year_button.click()
        popup.get_by_text(year_text, exact=True).last.click()
        self._pause()

        month_cell = popup.get_by_role("gridcell", name=month_name, exact=True)
        if month_cell.count() > 0:
            month_cell.last.click()
        else:
            popup.get_by_text(month_name, exact=True).last.click()
        try:
            popup.wait_for(state="hidden", timeout=5_000)
        except PlaywrightTimeoutError:
            # A minimum business-step pause still prevents the next picker from
            # being opened during the closing animation.
            pass
        self._wait_for_loading_to_finish(
            self.selectors.query_result_timeout_ms
        )
        self._pause()

    def _select_insurance(self, insurance_type: str) -> None:
        selector = self._required(self.selectors.insurance_type, "insurance_type")
        value = _INSURANCE_DISPLAY.get(insurance_type, insurance_type.removesuffix("保险"))
        locator = self.page.locator(selector).first
        try:
            tag_name = locator.evaluate("element => element.tagName")
            if str(tag_name).upper() == "SELECT":
                locator.select_option(label=value)
                self._wait_for_loading_to_finish(
                    self.selectors.query_result_timeout_ms
                )
                self._pause()
                return
            locator.click()
            option_selector = self._required(
                self.selectors.insurance_option_template,
                "insurance_option_template",
            ).replace("{value}", value)
            option = self.page.locator(option_selector).last
            option.click()
            try:
                option.wait_for(state="hidden", timeout=5_000)
            except PlaywrightTimeoutError:
                pass
            self._wait_for_loading_to_finish(
                self.selectors.query_result_timeout_ms
            )
            self._pause()
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"无法选择险种：{value}", details=str(exc)
            ) from exc

    def _wait_for_employee_row(self, record: EmployeeRecord) -> Locator:
        scope = self._candidate_table()
        rows = scope.get_by_role("row").filter(has_text=record.name)
        no_results = scope.locator(self.selectors.no_results).first
        loading = self.page.locator(self.selectors.loading_indicator).first
        started = time.monotonic()
        spinner_seen = False
        visible_rows: list[Locator] = []

        while (time.monotonic() - started) * 1000 < self.selectors.query_result_timeout_ms:
            self._raise_if_cancelled()
            if self.selectors.loading_indicator and self._visible(loading):
                spinner_seen = True
                self.page.wait_for_timeout(200)
                continue

            visible_rows = [
                rows.nth(index)
                for index in range(rows.count())
                if self._visible(rows.nth(index))
            ]
            if visible_rows:
                if not record.identity_number:
                    if len(visible_rows) == 1:
                        return visible_rows[0]
                    raise MultipleEmployeeMatchedError(
                        f"第 {record.row_number} 行姓名匹配到多个人员"
                    )

                identity = record.identity_number.upper()
                matched = []
                for row in visible_rows:
                    text = re.sub(r"\s+", "", row.inner_text()).upper()
                    if identity in text or identity[-4:] in text:
                        matched.append(row)
                if len(matched) == 1:
                    return matched[0]
                if len(matched) > 1:
                    raise MultipleEmployeeMatchedError(
                        f"第 {record.row_number} 行身份证匹配到多个人员"
                    )
                if (
                    (time.monotonic() - started) * 1000
                    >= self.selectors.no_result_confirm_ms
                ):
                    raise EmployeeNotFoundError(
                        f"第 {record.row_number} 行姓名存在，但身份证无法匹配"
                    )

            elapsed_ms = (time.monotonic() - started) * 1000
            no_result_is_final = elapsed_ms >= self.selectors.no_result_confirm_ms
            if (
                self.selectors.no_results
                and no_result_is_final
                and self._visible(no_results)
            ):
                raise EmployeeNotFoundError(
                    f"第 {record.row_number} 行没有查询到人员"
                )
            self.page.wait_for_timeout(250)

        raise QueryResultTimeoutError(
            f"第 {record.row_number} 行等待查询结果超时"
        )

    def _candidate_table(self) -> Locator:
        if self.selectors.candidate_table:
            table = self.page.locator(self.selectors.candidate_table).last
            table.wait_for(state="visible")
            return table

        # The left query table is the leftmost visible Ant Design table. This
        # deliberately excludes historical rows in the selected table on the right.
        tables = self.page.locator(".ant-table-wrapper")
        visible: list[tuple[float, Locator]] = []
        for index in range(tables.count()):
            table = tables.nth(index)
            if not self._visible(table):
                continue
            box = table.bounding_box()
            if box is not None:
                visible.append((box["x"], table))
        if not visible:
            raise WebsiteStructureChangedError("没有找到左侧人员查询结果表格")
        return min(visible, key=lambda item: item[0])[1]

    def _wait_until_transferred(self, record: EmployeeRecord) -> None:
        """Waits for the selected-side table to contain the transferred employee."""
        if not self.selectors.selected_table:
            self._wait_for_spinner_to_finish(
                self.selectors.transfer_result_timeout_ms
            )
            return

        table = self.page.locator(self.selectors.selected_table).last
        deadline = time.monotonic() + self.selectors.transfer_result_timeout_ms / 1000
        spinner_seen = False
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            loading = self.page.locator(self.selectors.loading_indicator).first
            if self.selectors.loading_indicator and self._visible(loading):
                spinner_seen = True
                self.page.wait_for_timeout(200)
                continue
            rows = table.get_by_role("row").filter(has_text=record.name)
            if any(
                self._visible(rows.nth(index)) for index in range(rows.count())
            ):
                # Let Ant Design finish checkbox/selection state updates.
                self.page.wait_for_timeout(300 if spinner_seen else 600)
                self._pause()
                return
            self.page.wait_for_timeout(200)
        raise QueryResultTimeoutError(
            f"第 {record.row_number} 行左移后未出现在已选列表"
        )

    def _wait_for_spinner_to_finish(self, timeout_ms: int) -> None:
        self._wait_for_loading_to_finish(timeout_ms)

    def _wait_for_loading_to_finish(self, timeout_ms: int) -> None:
        """Waits until all loading masks are gone and the state stays stable."""
        if not self.selectors.loading_indicator:
            self.page.wait_for_timeout(600)
            return
        spinners = self.page.locator(self.selectors.loading_indicator)
        deadline = time.monotonic() + timeout_ms / 1000
        stable_samples = 0
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            visible = any(
                self._visible(spinners.nth(index))
                for index in range(spinners.count())
            )
            if visible:
                stable_samples = 0
            else:
                stable_samples += 1
                if stable_samples >= 3:
                    # Final buffer covers the loading-mask exit animation and
                    # prevents the next field click from racing a DOM repaint.
                    self.page.wait_for_timeout(300)
                    return
            self.page.wait_for_timeout(150)
        raise QueryResultTimeoutError("等待页面加载完成超时")

    def _select_all_chosen_people(self) -> None:
        table = self._selected_table()
        table.wait_for(state="visible")
        native_checkbox = table.locator(
            ".ant-table-thead input[type=checkbox]"
        ).first
        if native_checkbox.count() > 0:
            native_checkbox.check(force=True)
            return
        table.locator(".ant-table-thead .ant-checkbox-wrapper").first.click()

    def _select_current_group(
        self,
        records: list[EmployeeRecord] | tuple[EmployeeRecord, ...],
    ) -> None:
        """Selects only this export group without clearing historical rows."""
        table = self._selected_table()
        table.wait_for(state="visible")
        row_checkboxes = table.locator(
            ".ant-table-tbody input[type=checkbox]"
        )
        changed = False
        for index in range(row_checkboxes.count()):
            checkbox = row_checkboxes.nth(index)
            if checkbox.is_checked():
                checkbox.uncheck(force=True)
                changed = True
        if changed:
            self.page.wait_for_timeout(300)

        for record in records:
            rows = table.get_by_role("row").filter(has_text=record.name)
            visible_rows = [
                rows.nth(index)
                for index in range(rows.count())
                if self._visible(rows.nth(index))
            ]
            if record.identity_number and len(visible_rows) > 1:
                identity = record.identity_number.upper()
                visible_rows = [
                    row
                    for row in visible_rows
                    if identity in re.sub(r"\s+", "", row.inner_text()).upper()
                    or identity[-4:]
                    in re.sub(r"\s+", "", row.inner_text()).upper()
                ]
            if len(visible_rows) != 1:
                raise WebsiteStructureChangedError(
                    f"右侧已选列表无法唯一定位第 {record.row_number} 行人员"
                )
            self._check_row(visible_rows[0])

    def _selected_table(self) -> Locator:
        if self.selectors.selected_table:
            return self.page.locator(self.selectors.selected_table).last
        return self.page.locator(".ant-table-wrapper").last

    def _selected_table_is_empty(self, table: Locator) -> bool:
        no_data = table.get_by_text("暂无数据", exact=False).first
        if self._visible(no_data):
            return True
        rows = table.locator(
            ".ant-table-tbody > tr:not(.ant-table-placeholder)"
        )
        return not any(
            self._visible(rows.nth(index)) for index in range(rows.count())
        )

    def _close_preview_if_visible(self) -> None:
        if not self.selectors.preview_dialog:
            return
        dialog = self.page.locator(self.selectors.preview_dialog).last
        if not self._visible(dialog) or not self.selectors.close_preview:
            return
        self._dismiss_preview(dialog)

    def _dismiss_preview(self, dialog: Locator) -> None:
        """Closes a preview without inheriting Playwright's 30-second timeout."""
        if not self._visible(dialog) or not self.selectors.close_preview:
            return
        close = dialog.locator(self.selectors.close_preview).first
        if not self._visible(close):
            return
        try:
            close.click(timeout=2_000, no_wait_after=True)
        except PlaywrightError:
            # During Ant Design's closing animation the node can be reported as
            # visible but never become stable. A DOM click avoids a 30s stall.
            try:
                close.evaluate("element => element.click()")
            except PlaywrightError:
                pass
        try:
            dialog.wait_for(state="hidden", timeout=3_000)
        except PlaywrightTimeoutError:
            _LOGGER.info("预览弹窗关闭动画未在3秒内结束，继续后续页面恢复")
        except PlaywrightError:
            # A detached modal means the close already completed.
            pass

    def _invalidate_filter_cache(self) -> None:
        self._current_insurance = None
        self._current_start_month = None
        self._current_end_month = None
        self._prepared_person_key = None

    @staticmethod
    def _check_row(row: Locator) -> None:
        checkbox = row.get_by_role("checkbox").first
        if checkbox.count() > 0:
            checkbox.check()
            return
        label = row.locator("label").first
        if label.count() > 0:
            label.click()
            return
        raise WebsiteStructureChangedError("人员结果行中没有找到复选框")

    def _click_if_visible(self, selector: str) -> None:
        if not selector:
            return
        locator = self.page.locator(selector).last
        if locator.count() > 0 and locator.is_visible():
            locator.click()
            self._pause()

    def _pause(self, minimum_ms: int | None = None) -> None:
        delay = self.selectors.step_delay_ms
        if minimum_ms is not None:
            delay = max(delay, minimum_ms)
        if delay > 0:
            self.page.wait_for_timeout(delay)
        self._raise_if_cancelled()

    def _raise_if_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise TaskCancelledError("用户提前停止任务")

    @staticmethod
    def _visible(locator: Locator) -> bool:
        try:
            return locator.count() > 0 and locator.is_visible()
        except PlaywrightError:
            return False

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not value:
            raise WebsiteStructureChangedError(f"{name} 定位器尚未配置")
        return value
