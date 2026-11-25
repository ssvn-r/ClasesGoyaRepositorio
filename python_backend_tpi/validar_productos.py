import json
from typing import Any, Optional


def validar_datos(nombre_archivo: str) -> Optional[list[dict[str, Any]]]:
    """Valida la estructura JSON y que cada producto tenga un precio numérico."""
    try:
        with open(nombre_archivo, "r", encoding="utf-8") as archivo_json:
            datos = json.load(archivo_json)

        if not isinstance(datos, list):
            raise ValueError("El archivo no contiene una lista de datos.")

        for item in datos:
            if not isinstance(item, dict):
                raise TypeError("Cada producto debe ser un objeto.")
            if not isinstance(item.get("precio"), (int, float)):
                raise TypeError(
                    f"El precio del producto '{item.get('nombre')}' no es numérico."
                )

        print("Validación exitosa.")
        return datos
    except FileNotFoundError:
        print(f"Error: El archivo '{nombre_archivo}' no se encontró.")
    except json.JSONDecodeError:
        print("Error: El archivo no tiene un formato JSON válido.")
    except (ValueError, TypeError) as error:
        print(f"Error en la validación de datos: {error}")

    return None
