import json
import os
import re
from openai import AzureOpenAI

class GibsonMetadataInference:
    def __init__(self, input_text):
        self.text = input_text

        self.client = AzureOpenAI(
            api_key="51964627c77d4f8ba1f6a305f5812aad",  
            api_version="2023-12-01-preview",
            azure_endpoint="https://cloudcourtoai.openai.azure.com/"
        )

    def generate_structure(self):
        # Unified prompt for extracting all required information
        prompt = """You are an expert in analyzing legal documents. Extract the following details from the text and return them in the given JSON format:
        {
            "witness_name": [Name of the witness],
            "transcript_date": [ISO date in MM-dd-yyyy format],
            "case_name": [The case name],
            "case_number": [The case number],
            "jurisdiction": [Court jurisdiction name],
            "witness_type": [Type of the witness],
            "taking_attorney": {"name": [Name of the taking attorney], "law_firm": [Law firm of the taking attorney]},
            "defending_attorney": {"name": [Name of the defending attorney], "law_firm": [Law firm of the defending attorney]}
        }
        Ensure that all fields are filled, even if it means inferring from context and only return a valid JSON and no extra explanation"""

        try:
            # Get raw string from OpenAI
            raw_response = self.client.chat.completions.create(
                model="SummarizeAI",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": self.text}
                ]
            ).choices[0].message.content


            # Strip triple backticks and 'json' identifier if present
            cleaned = re.sub(r"^```json|```$", "", raw_response.strip(), flags=re.IGNORECASE).strip()

            # Now parse the cleaned string into a dict
            extracted_data = json.loads(cleaned)

        except Exception as e:
            extracted_data = {}
            print("Exception", e)



        # Reformat the witness name as "LastName, FirstName" with proper capitalization
        print("Hello")
        def format_name(name):
            pattern = r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Hon\.|Prof\.)\s+'
            cleaned = re.sub(pattern, '', name or '', flags=re.IGNORECASE).strip()
            if not cleaned:
                return ""
            parts = cleaned.split()
            if len(parts) >= 2:
                first_name = ' '.join(parts[:-1]).title()
                last_name = parts[-1].title()
                return f"{last_name}, {first_name}"
            return cleaned.title()
        # Process witness name
        raw_witness_name = extracted_data.get("witness_name", "").strip()
        witness_name = format_name(raw_witness_name)
        print("Hello3",witness_name)
        # print("Hello2")

        # # Process taking attorney

        # raw_taking_attorney_name = extracted_data.get("taking_attorney", {}).get("name", "").strip()
        # print("taking_attorney_name",taking_attorney_name)
        # taking_attorney_name = format_name(raw_taking_attorney_name)

        # # Process defending attorney
        # raw_defending_attorney_name = extracted_data.get("defending_attorney", {}).get("name", "").strip()
        # defending_attorney_name = format_name(raw_defending_attorney_name)
        # print("extracted_data_____222", extracted_data.get('witness_name'))
        return {
            "witness_name": extracted_data.get("witness_name"),
            "transcript_date": extracted_data.get("transcript_date", ""),
            "case_name": extracted_data.get("case_name", ""),
            "case_number": extracted_data.get("case_number", ""),
            "jurisdiction": extracted_data.get("jurisdiction", ""),
            "taking_attorney": extracted_data.get("taking_attorney", {"name": "", "law_firm": ""}),
            "defending_attorney": extracted_data.get("defending_attorney", {"name": "", "law_firm": ""}),
            "witness_type":extracted_data.get("witness_ype","")

        }
