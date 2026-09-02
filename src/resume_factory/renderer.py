import os
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

class ResumeRenderer:
    def __init__(self, template_dir: str = "templates", output_dir: str = "output"):
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        
        os.makedirs(os.path.join(output_dir, "resumes"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "cover_letters"), exist_ok=True)

    def _slugify(self, text: str) -> str:
        text = str(text).lower()
        return re.sub(r'[\W_]+', '_', text).strip('_')

    async def render_resume_pdf(self, tailored_content: dict, job_id: str, company: str) -> str:
        template = self.jinja_env.get_template("resume_template.html")
        html_content = template.render(**tailored_content)
        
        slug = self._slugify(company)
        filename = f"{job_id}_{slug}_resume.pdf"
        output_path = os.path.join(self.output_dir, "resumes", filename)
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            css_path = os.path.join(self.template_dir, "resume_styles.css")
            with open(css_path, "r", encoding="utf-8") as f:
                css_content = f.read()
                
            html_content = html_content.replace(
                '<link rel="stylesheet" href="resume_styles.css">',
                f"<style>\n{css_content}\n</style>"
            )
            
            await page.set_content(html_content)
            await page.pdf(path=output_path, format="A4", print_background=True)
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
