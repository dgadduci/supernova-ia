from dataclasses import dataclass
import json

import requests


@dataclass
class QueryLlm :
    prompt : str #se debe pasar por parametro
    message : str =None#se debe pasar por parametro
    url: str = "http://100.113.65.40:11434/api/generate" 
    model_name: str = "qwen-27b-coding:latest"    
    _payload :dict = None
    
    def __post_init__(self) :
        self._payload = {
            "model": self.model_name,
            "prompt": self.prompt,
            "message": self.message,
            "stream": False,          
            "keep_alive": "2h",       
            "think": False,           
            "format": "json",         
            "options": {
                "temperature": 0,     
                "num_predict": 1500,   
                "num_ctx": 8192       
            }
        }

    def request_llm(self, message : str) -> dict :
        response = requests.post(
            self.url,
            json= self._payload, 
            timeout=180  
        )
        response.raise_for_status()

        data = response.json()
        response_text = data.get("response", "")
        return self._json_extract(response_text)
    
    def _json_extract(self, texto: str) -> dict:
        texto = texto.strip()

        if not texto:
            raise ValueError("La respuesta del modelo vino vacía.")

        try:
            # Intento de parse directo (funciona si la salida es limpia)
            return json.loads(texto)
        except json.JSONDecodeError:
            inicio = texto.find("{")
            fin = texto.rfind("}")

            if inicio == -1 or fin == -1 or fin <= inicio:
                raise ValueError("No se encontró un objeto JSON en la respuesta del modelo.")

            # Extrae substring entre el primer '{' y el último '}' para eliminar Markdown/relleno
            return json.loads(texto[inicio:fin + 1])






