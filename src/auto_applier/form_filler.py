import logging
import os

MODAL = "div.jobs-easy-apply-modal, div[role='dialog']"


class FormFiller:
    def __init__(self, qa_system, profile: dict):
        self.qa = qa_system
        self.profile = profile

    async def fill_form_page(self, page, resume_path: str | None = None) -> list[str]:
        """Fill every visible, empty field on the current Easy Apply step."""
        filled: list[str] = []
        scope = page.locator(MODAL).first
        if await scope.count() == 0:
            scope = page

        await self._fill_text_inputs(scope, filled)
        await self._fill_textareas(scope, filled)
        await self._fill_selects(scope, filled)
        await self._fill_radios(scope, filled)
        if resume_path:
            await self._upload_resume(scope, resume_path, filled)
        return filled

    async def _label_for(self, element) -> str:
        for attr in ("aria-label", "name", "id", "placeholder"):
            value = await element.get_attribute(attr)
            if value:
                return value.replace("-", " ").replace("_", " ").strip()
        return ""

    async def _fill_text_inputs(self, scope, filled: list[str]) -> None:
        inputs = scope.locator("input[type='text'], input[type='number'], input[type='tel'], input[type='email']")
        for i in range(await inputs.count()):
            field = inputs.nth(i)
            try:
                if not await field.is_visible() or await field.input_value():
                    continue
                label = await self._resolve_label(scope, field)
                field_type = await field.get_attribute("type") or "text"
                answer = self.qa.get_answer(label, field_type)
                if answer:
                    await field.fill(str(answer))
                    filled.append(label)
            except Exception as exc:
                logging.debug("Skipped text input: %s", exc)

    async def _fill_textareas(self, scope, filled: list[str]) -> None:
        areas = scope.locator("textarea")
        for i in range(await areas.count()):
            field = areas.nth(i)
            try:
                if not await field.is_visible() or await field.input_value():
                    continue
                label = await self._resolve_label(scope, field)
                answer = self.qa.get_answer(label, "textarea")
                if answer:
                    await field.fill(str(answer))
                    filled.append(label)
            except Exception as exc:
                logging.debug("Skipped textarea: %s", exc)

    async def _fill_selects(self, scope, filled: list[str]) -> None:
        selects = scope.locator("select")
        for i in range(await selects.count()):
            field = selects.nth(i)
            try:
                if not await field.is_visible():
                    continue
                options = [o.strip() for o in await field.locator("option").all_inner_texts() if o.strip()]
                real = [o for o in options if o.lower() not in ("select an option", "choose", "")]
                if not real:
                    continue
                if (await field.input_value() or "").strip():
                    continue
                label = await self._resolve_label(scope, field)
                answer = self.qa.get_answer(label, "select", real)
                choice = next((o for o in real if answer and answer.lower() in o.lower()), real[0])
                await field.select_option(label=choice)
                filled.append(label)
            except Exception as exc:
                logging.debug("Skipped select: %s", exc)

    async def _fill_radios(self, scope, filled: list[str]) -> None:
        groups = scope.locator("fieldset[data-test-form-builder-radio-button-form-component]")
        for i in range(await groups.count()):
            group = groups.nth(i)
            try:
                if await group.locator("input[type='radio']:checked").count() > 0:
                    continue
                legend = (await group.locator("legend").first.inner_text()).strip()
                options = [o.strip() for o in await group.locator("label").all_inner_texts() if o.strip()]
                if not options:
                    continue
                answer = self.qa.get_answer(legend, "radio", options)
                choice = next((o for o in options if answer and answer.lower() in o.lower()), options[0])
                await group.locator("label", has_text=choice).first.click()
                filled.append(legend)
            except Exception as exc:
                logging.debug("Skipped radio group: %s", exc)

    async def _upload_resume(self, scope, resume_path: str, filled: list[str]) -> None:
        if not os.path.exists(resume_path):
            return
        uploads = scope.locator("input[type='file']")
        for i in range(await uploads.count()):
            try:
                await uploads.nth(i).set_input_files(os.path.abspath(resume_path))
                filled.append("resume upload")
                return
            except Exception as exc:
                logging.debug("Skipped file input: %s", exc)

    async def _resolve_label(self, scope, field) -> str:
        field_id = await field.get_attribute("id")
        if field_id:
            try:
                label = scope.locator(f'label[for="{field_id}"]').first
                if await label.count() > 0:
                    text = (await label.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                pass
        return await self._label_for(field)
