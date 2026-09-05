# LLM Knowledge Extractor - MinerU

Sends file resources to a configured MinerU HTTP service and stores its JSON output.

```bash
python3 -m pip install requests
odoo-bin -d your_database -i llm_knowledge_extractor_mineru
```

Create a `mineru` extractor record and configure its API URL and optional API key.
Source document bytes are transmitted to that configured service.
