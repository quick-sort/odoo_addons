import base64

import pymupdf

from odoo import models


class LLMResourceParser(models.Model):
    _inherit = "llm.resource"

    def _get_parser(self, record, field_name, mimetype):
        if self.parser == "default" and mimetype == "application/pdf":
            return self._parse_pdf
        return super()._get_parser(record, field_name, mimetype)

    def _parse_pdf(self, record, field):
        if field["mimetype"] != "application/pdf":
            return False

        text_content = []
        with pymupdf.open(stream=field["rawcontent"], filetype="pdf") as document:
            for page_number, page in enumerate(document):
                text_content.append(
                    f"## Page {page_number + 1}\n\n{page.get_text()}"
                )
                for image_index, image in enumerate(page.get_images(full=True)):
                    try:
                        base_image = document.extract_image(image[0])
                        if not base_image:
                            continue
                        image_name = (
                            f"image_{page_number}_{image_index}.{base_image['ext']}"
                        )
                        attachment = record.env["ir.attachment"].create(
                            {
                                "name": image_name,
                                "datas": base64.b64encode(base_image["image"]),
                                "res_model": "llm.resource",
                                "res_id": self.id,
                                "mimetype": f"image/{base_image['ext']}",
                            }
                        )
                        text_content.append(
                            f"\n![{image_name}](/web/image/{attachment.id})\n"
                        )
                    except Exception as error:  # noqa: BLE001
                        self._post_styled_message(
                            f"Error extracting image: {error}", "warning"
                        )

        self._write_content_to_backend("\n\n".join(text_content))
        return True
