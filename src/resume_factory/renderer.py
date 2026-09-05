import os
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

from src.settings import OUTPUT_DIR, TEMPLATE_DIR

CM_TO_PX = 96 / 2.54
PAGE_MARGIN_CM = {"top": 1.3, "right": 1.5, "bottom": 1.3, "left": 1.5}
PDF_MARGIN = {side: f"{cm}cm" for side, cm in PAGE_MARGIN_CM.items()}

# A4 at 96 CSS px per inch, minus the print margins.
PRINTABLE_WIDTH_PX = round(794 - (PAGE_MARGIN_CM["left"] + PAGE_MARGIN_CM["right"]) * CM_TO_PX)
PRINTABLE_HEIGHT_PX = round(1123 - (PAGE_MARGIN_CM["top"] + PAGE_MARGIN_CM["bottom"]) * CM_TO_PX)


class ResumeRenderer:
    def __init__(self, template_dir: str = None, output_dir: str = None):
        self.template_dir = template_dir or TEMPLATE_DIR
        self.output_dir = output_dir or OUTPUT_DIR
        self.jinja_env = Environment(loader=FileSystemLoader(self.template_dir), autoescape=True)

        os.makedirs(os.path.join(self.output_dir, "resumes"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "cover_letters"), exist_ok=True)

    def _slugify(self, text: str) -> str:
        text = str(text).lower()
        return re.sub(r'[\W_]+', '_', text).strip('_')

    def _build_resume_html(self, content: dict, include_education: bool) -> str:
        template = self.jinja_env.get_template("resume_template.html")
        html_content = template.render({**content, "include_education": include_education})

        css_path = os.path.join(self.template_dir, "resume_styles.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

        return html_content.replace(
            '<link rel="stylesheet" href="resume_styles.css">',
            f"<style>\n{css_content}\n</style>"
        )

    @staticmethod
    async def _content_height(page) -> float:
        return await page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        )

    async def render_resume_pdf(self, tailored_content: dict, job_id: str, company: str) -> str:
        slug = self._slugify(company)
        filename = f"{job_id}_{slug}_resume.pdf"
        output_path = os.path.join(self.output_dir, "resumes", filename)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": PRINTABLE_WIDTH_PX, "height": PRINTABLE_HEIGHT_PX}
            )
            await page.emulate_media(media="print")

            await page.set_content(self._build_resume_html(tailored_content, include_education=False))
            # Education is omitted while it would cost a second page, and added back once
            # the resume is spilling onto one anyway.
            if await self._content_height(page) > PRINTABLE_HEIGHT_PX:
                await page.set_content(
                    self._build_resume_html(tailored_content, include_education=True)
                )

            await page.pdf(path=output_path, format="A4", print_background=True, margin=PDF_MARGIN)
            await browser.close()

        return output_path

    async def render_cover_letter_pdf(self, cover_letter_text: str, personal_info: dict, 
                                       job_title: str, company: str, job_id: str) -> str:
        template = self.jinja_env.get_template("cover_letter_template.html")
        
        data = {
            "name": personal_info.get("name", ""),
            "email": personal_info.get("email", ""),
            "phone": personal_info.get("phone", ""),
            "location": personal_info.get("location", ""),
            "linkedin_url": personal_info.get("linkedin_url", ""),
            "date": datetime.now().strftime("%B %d, %Y"),
            "company": company,
            "job_title": job_title,
            "body": cover_letter_text
        }
        
        html_content = template.render(**data)
        
        slug = self._slugify(company)
        filename = f"{job_id}_{slug}_cover.pdf"
        output_path = os.path.join(self.output_dir, "cover_letters", filename)
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content)
            await page.pdf(path=output_path, format="A4", print_background=True)
            await browser.close()
            
        return output_path
