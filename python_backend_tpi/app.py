import csv
import json
from pathlib import Path

from validar_productos import validar_datos


BASE_DIR = Path(__file__).parent

productos = [
    {"nombre": "Laptop", "precio": 1200, "stock": 15},
    {"nombre": "Mouse", "precio": 25, "stock": 5},
    {"nombre": "Teclado", "precio": 75, "stock": 25},
    {"nombre": "Monitor", "precio": 300, "stock": 8},
]

productos_bajo_stock = []
for producto in productos:
    print(f"Producto: {producto['nombre']}, Precio: ${producto['precio']}")
    if producto["stock"] < 10:
        productos_bajo_stock.append(producto)

print("\nProductos con bajo stock:")
print(productos_bajo_stock)


def calcular_promedio_precio(lista: list[dict[str, int]]) -> float:
    if not lista:
        return 0
    total_precio = sum(producto["precio"] for producto in lista)
    return total_precio / len(lista)


precio_promedio = calcular_promedio_precio(productos)
print(f"\nEl precio promedio de los productos es: ${precio_promedio:.2f}")

productos_desde_csv = []
try:
    with open(BASE_DIR / "datos.csv", mode="r", encoding="utf-8") as archivo_csv:
        lector_diccionario = csv.DictReader(archivo_csv)
        for fila in lector_diccionario:
            fila["id"] = int(fila["id"])
            fila["precio"] = int(fila["precio"])
            fila["stock"] = int(fila["stock"])
            productos_desde_csv.append(fila)
except FileNotFoundError:
    print("Error: El archivo 'datos.csv' no se encontró.")

if productos_desde_csv:
    ruta_salida = BASE_DIR / "salida.json"
    with open(ruta_salida, "w", encoding="utf-8") as archivo_salida:
        json.dump(productos_desde_csv, archivo_salida, indent=4, ensure_ascii=False)

    print("\nArchivo 'salida.json' creado con éxito.")
    print("\n--- Ejecutando el validador modular ---")
    datos_validados = validar_datos(str(ruta_salida))
    if datos_validados is not None:
        print("Datos validados correctamente:", datos_validados)
