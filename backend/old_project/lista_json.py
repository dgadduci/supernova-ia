import json

productos =[
  { "id": 1, "idcategoria": 101, "nombre_producto": "Pizza Pepperoni", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.50, "disponible": True },
  { "id": 2, "idcategoria": 101, "nombre_producto": "Pizza Pepperoni", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 14.00, "disponible": True },
  { "id": 3, "idcategoria": 101, "nombre_producto": "Pizza Margarita", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 7.50, "disponible": True },
  { "id": 4, "idcategoria": 101, "nombre_producto": "Pizza Margarita", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 12.50, "disponible": True },
  { "id": 5, "idcategoria": 101, "nombre_producto": "Pizza Napolitana", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.00, "disponible": True },
  { "id": 6, "idcategoria": 101, "nombre_producto": "Pizza Napolitana", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 13.50, "disponible": True },
  { "id": 7, "idcategoria": 101, "nombre_producto": "Pizza Cuatro Quesos", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.00, "disponible": True },
  { "id": 8, "idcategoria": 101, "nombre_producto": "Pizza Cuatro Quesos", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.00, "disponible": True },
  { "id": 9, "idcategoria": 101, "nombre_producto": "Pizza Jamón y Champiñones", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.75, "disponible": True },
  { "id": 10, "idcategoria": 101, "nombre_producto": "Pizza Jamón y Champiñones", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 14.25, "disponible": True },
  { "id": 11, "idcategoria": 101, "nombre_producto": "Pizza Vegetariana", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.25, "disponible": True },
  { "id": 12, "idcategoria": 101, "nombre_producto": "Pizza Vegetariana", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 13.75, "disponible": True },
  { "id": 13, "idcategoria": 101, "nombre_producto": "Pizza Hawaiana", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.50, "disponible": True },
  { "id": 14, "idcategoria": 101, "nombre_producto": "Pizza Hawaiana", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 14.00, "disponible": True },
  { "id": 15, "idcategoria": 101, "nombre_producto": "Pizza Carnívora", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.50, "disponible": True },
  { "id": 16, "idcategoria": 101, "nombre_producto": "Pizza Carnívora", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.50, "disponible": True },
  { "id": 17, "idcategoria": 101, "nombre_producto": "Pizza Rústica", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.25, "disponible": True },
  { "id": 18, "idcategoria": 101, "nombre_producto": "Pizza Rústica", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.25, "disponible": True },
  { "id": 19, "idcategoria": 101, "nombre_producto": "Pizza Pollo y Cebolla", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.75, "disponible": True },
  { "id": 20, "idcategoria": 101, "nombre_producto": "Pizza Pollo y Cebolla", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 14.25, "disponible": True },
  { "id": 21, "idcategoria": 101, "nombre_producto": "Pizza Mozzarella con Albahaca", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.00, "disponible": True },
  { "id": 22, "idcategoria": 101, "nombre_producto": "Pizza Mozzarella con Albahaca", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 13.50, "disponible": True },
  { "id": 23, "idcategoria": 101, "nombre_producto": "Pizza Pesto y Pollo", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.00, "disponible": True },
  { "id": 24, "idcategoria": 101, "nombre_producto": "Pizza Pesto y Pollo", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.00, "disponible": True },
  { "id": 25, "idcategoria": 101, "nombre_producto": "Pizza Prosciutto e Funghi", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.25, "disponible": True },
  { "id": 26, "idcategoria": 101, "nombre_producto": "Pizza Prosciutto e Funghi", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.25, "disponible": True },
  { "id": 27, "idcategoria": 101, "nombre_producto": "Pizza Diavola", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.75, "disponible": True },
  { "id": 28, "idcategoria": 101, "nombre_producto": "Pizza Diavola", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 14.25, "disponible": True },
  { "id": 29, "idcategoria": 101, "nombre_producto": "Pizza Capricciosa", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 8.75, "disponible": True },
  { "id": 30, "idcategoria": 101, "nombre_producto": "Pizza Capricciosa", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 14.25, "disponible": True },
  { "id": 31, "idcategoria": 101, "nombre_producto": "Pizza Quattro Stagioni", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.00, "disponible": True },
  { "id": 32, "idcategoria": 101, "nombre_producto": "Pizza Quattro Stagioni", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.00, "disponible": True },
  { "id": 33, "idcategoria": 101, "nombre_producto": "Pizza Funghi e Tartufo", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.50, "disponible": True },
  { "id": 34, "idcategoria": 101, "nombre_producto": "Pizza Funghi e Tartufo", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 16.00, "disponible": True },
  { "id": 35, "idcategoria": 101, "nombre_producto": "Pizza Salsiccia y Rucola", "nombre_categoria": "Pizzas", "tamanio": "chica", "precio": 9.25, "disponible": True },
  { "id": 36, "idcategoria": 101, "nombre_producto": "Pizza Salsiccia y Rucola", "nombre_categoria": "Pizzas", "tamanio": "grande", "precio": 15.75, "disponible": True },
  { "id": 37, "idcategoria": 201, "nombre_producto": "Empanada de Carne", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.50, "disponible": True },
  { "id": 38, "idcategoria": 201, "nombre_producto": "Empanada de Pollo", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.40, "disponible": True },
  { "id": 39, "idcategoria": 201, "nombre_producto": "Empanada de Jamón y Queso", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.60, "disponible": True },
  { "id": 40, "idcategoria": 201, "nombre_producto": "Empanada de Verduras", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.35, "disponible": True },
  { "id": 41, "idcategoria": 201, "nombre_producto": "Empanada de Atún y Queso", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.55, "disponible": True },
  { "id": 42, "idcategoria": 201, "nombre_producto": "Empanada de Carne Mechada", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.70, "disponible": True },
  { "id": 43, "idcategoria": 201, "nombre_producto": "Empanada de Pollo y Champiñones", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.65, "disponible": True },
  { "id": 44, "idcategoria": 201, "nombre_producto": "Empanada de Queso Azul", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.80, "disponible": True },
  { "id": 45, "idcategoria": 201, "nombre_producto": "Empanada de Espinaca y Ricotta", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.60, "disponible": True },
  { "id": 46, "idcategoria": 201, "nombre_producto": "Empanada de Chorizo", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.75, "disponible": True },
  { "id": 47, "idcategoria": 201, "nombre_producto": "Empanada de Pavo y Queso", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.65, "disponible": True },
  { "id": 48, "idcategoria": 201, "nombre_producto": "Empanada de Calabaza", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.45 , "disponible": True},
  { "id": 49, "idcategoria": 201, "nombre_producto": "Empanada de Carne y Aceitunas", "nombre_categoria": "Empanadas", "tamanio": "unidad", "precio": 1.70 , "disponible": True},
  { "id": 50, "idcategoria": 301, "nombre_producto": "Coca Cola", "nombre_categoria": "Bebidas", "tamanio": "lata", "precio": 2.00 , "disponible": False},
  { "id": 51, "idcategoria": 301, "nombre_producto": "Coca Cola", "nombre_categoria": "Bebidas", "tamanio": "1 litro", "precio": 2.00 , "disponible": True},
  { "id": 52, "idcategoria": 301, "nombre_producto": "Sprite", "nombre_categoria": "Bebidas", "tamanio": "lata", "precio": 2.00 , "disponible": True},
]

import json

tipos_medios_de_pago = [
    {
        "id": 1,
        "descripcion": "efectivo"
    },
    {
        "id": 2,
        "descripcion": "transferencia"
    },
    {
        "id": 3,
        "descripcion": "tarjeta de debito"
    },
    {
        "id": 4,
        "descripcion": "tarjeta de credito"
    }
]

medios_de_pago = [
    {
        "id": 1,
        "id_tipo": 1,
        "descripcion": "efectivo",
        "titular": "",
        "alias": "",
        "activo": True  # Nueva llave agregada
    },
    {
        "id": 2,
        "id_tipo": 2,
        "descripcion": "transferencia",
        "titular": "Alberto Mosquera",
        "alias": "alberto.mp",
        "activo": True  # Nueva llave agregada
    },
    {
        "id": 3,
        "id_tipo": 2,
        "descripcion": "transferencia",
        "titular": "Mirtha Bruno",
        "alias": "mirtha.mp",
        "activo": False  # Nueva llave agregada
    }
]

metodos_entrega = [
  {
    "id": 1,
    "descripcion": "retira_local",
    "activo": True
  },
  {
    "id": 2,
    "descripcion": "delivery",
    "activo": True
  },
  {
    "id": 3,
    "descripcion": "consume_salon",
    "activo": False
  }
]