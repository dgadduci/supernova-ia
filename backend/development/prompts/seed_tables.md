Aprovechando que ya conoces los modelos en backend/models/, crea el seed para la tabla metodos_entrega aplicando la separación de responsabilidades:
	1	Crea el archivo JSON en backend/db/seeds/data/metodos_entrega.json con los registros iniciales correspondientes a la estructura de ese modelo, con los metodos retiro en local, delivery y consumo en salon
	2	Crea el script Python idempotente en backend/db/seeds/seeds/metodos_entrega.py que lea ese JSON y persista los registros en las base de datos supernova y supernova_test.
	3	En las especificaciones de OpenSpec (tasks.md / spec.md), documenta solo la capacidad del script de forma abstracta, sin listar los datos crudos."




Aprovechando que ya conoces los modelos en backend/models/, crea el seed para la tabla producto_presentaciones aplicando la separación de responsabilidades:
	1	Crea el archivo JSON en backend/db/seeds/data/producto_presentaciones.json con los registros iniciales correspondientes a la estructura de ese modelo. Para eso, debes usar todos los registros de la tabla productos y generar para dada producto pizza dos presentaciones (chica y grande) empanadas una presentacion (unidad) bebidas 3 presentaciones (lata, litro, 2 litros), postre presentacion kilo. 
	2	Debes verificar la integridad de los datos para lo cual deberas seguir las relaciones entre las tablas, verificando que la categoria, el producto y la presentacion correspondan al mismo comercio
	3	3 Crea el script Python idempotente en backend/db/seeds/seeds/producto_presentaciones.py que lea ese JSON y persista los registros en las base de datos supernova y supernova_test.
	4	4 En las especificaciones de OpenSpec (tasks.md / spec.md), documenta solo la capacidad del script de forma abstracta, sin listar los datos crudos."


Aprovechando que ya conoces los modelos en backend/models/, crea el seed para la tabla producto_precios aplicando la separación de responsabilidades:
	1	Crea el archivo JSON en backend/db/seeds/data/precios.json con los registros iniciales correspondientes a la estructura de ese modelo. Para ello deberas: 
	⁃	recorrer toda la tabla producto_presentaciones, obtener el id_producto, luego obtener por ese id_producto:
	⁃	 en la tabla productos la id_categoria_producto, luego con id_categoria_producto en la tabla categorias_productos obtener la categoria_producto. 
	⁃	en la tabla producto_presentaciones las presentaciones de ese producto
	⁃	crear el registro del precio de ese producto en la tabla producto_precios teniendo en cuenta la categoria del producto obtenida, con los siguientes parametros:
		- Categoria Pizzas presentacion CHICA valores entre 10000 y 20000 , GRANDE el doble de la presentacion CHICA de ese producto
		- Categoria Empanadas valores entre 3000 y 6000
		- Categoria Bebidas valores entre 4000 y 10000
		- Categoria Postres valores entre 8000 y 20000
	1	Crea el script Python idempotente en backend/db/seeds/seeds/producto_precios.py que lea ese JSON y persista los registros en las base de datos supernova y supernova_test.
	2	En las especificaciones de OpenSpec (tasks.md / spec.md), documenta solo la capacidad del script de forma abstracta, sin listar los datos crudos."