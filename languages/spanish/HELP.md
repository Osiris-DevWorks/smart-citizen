# Smart Citizen: guía de inicio rápido

> Esta página es una traducción proporcionada para tu comodidad. En caso de discrepancia, la versión en inglés prevalece. Estado de las traducciones: `languages/TRANSLATIONS.md`.

## Primera configuración

Al iniciarse, Smart Citizen recarga las personalizaciones de tu sesión anterior y busca tu instalación de Star Citizen: el instalador rellena esta ruta automáticamente, pero puedes cambiarla en la pestaña **Configuración**. Toda la localización original y los datos de DataForge provienen **directamente de tu `Data.p4k` instalado** (sin descargas, sin réplicas de la comunidad), así que extraer una vez es un primer paso obligatorio tras la instalación o tras cualquier parche del juego.

## Modo simple y modo avanzado

Smart Citizen se abre en uno de dos modos, y puedes cambiar en cualquier momento.

- El **modo simple** es una pantalla de dos botones: uno, **Aplicar mejoras**, ejecuta toda la cadena con tu configuración actual (extracción, generación y aplicación, con una copia de seguridad previa de tu archivo del juego); el otro cambia al **modo avanzado**. Es la vía rápida cuando solo quieres aplicar las mejoras sin editar textos a mano.
- El **modo avanzado** es la aplicación completa: la tabla de textos, los filtros, la pestaña Mejoras, la pestaña Configuración y todo lo demás de esta guía.

Elige tu modo predeterminado durante la instalación, o alterna entre ellos dentro de la aplicación. El modo simple usa la última configuración guardada en el avanzado.

## 1. Extraer la localización base desde Data.p4k

Abre la pestaña **Configuración** y haz clic en **Extraer desde Data.p4k**. Esto descomprime el `global.ini` original junto con los XML de entidades de DataForge que usa el generador de mejoras: naves, componentes, armas, misiones, blueprints, etc.

Cuando la extracción termina, el `base.ini` extraído se carga automáticamente en la tabla, fusionado con los archivos de mejoras y tus cambios guardados en `user.ini`.

## 2. Editar textos de localización

- Haz doble clic en cualquier celda de **Valor personalizado** para editar el texto.
- **Valor por defecto**: texto original del `base.ini` extraído de `Data.p4k`.
- **Valor actual**: el valor efectivo antes de tu cambio (base + capas INI importadas).
- **Valor personalizado**: tu edición personal. Se guarda automáticamente con cada cambio y se conserva en `<carpeta de datos>\<canal>\user.ini` (la carpeta de datos por defecto es `Documents\Smart Citizen`, y cada canal de Star Citizen — LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW — tiene sus propios cambios aislados).
- La columna **Estado** indica de dónde procede el valor actual de cada fila:
  - **Modificado**: editaste explícitamente el Valor personalizado.
  - **Mejorado**: generado automáticamente por el proceso de mejoras (superposiciones de estadísticas, etiquetas de blueprints, etc.).
  - **Sin modificar**: texto original del `base.ini`.
  - **Nuevo**: la clave solo existe en tus cambios o en el proceso de mejoras, no en el `base.ini` original.
- **Cambia el ancho de cualquier columna** arrastrando el separador entre dos encabezados, o haz doble clic en un separador para ajustar la columna al ancho de su contenido más largo. Tus anchos se recuerdan entre sesiones. Mientras no cambies nada tú mismo, Smart Citizen ajusta las columnas a tu ventana automáticamente, de modo que una instalación nueva siempre se abre correctamente en su propia pantalla. Para recuperar esa disposición automática, usa **Restablecer las proporciones de la ventana** (más abajo).

## 3. Panel de vista previa

El **panel de vista previa** en la esquina superior derecha muestra el texto renderizado de la fila seleccionada. Los tokens de localización del juego se convierten en HTML con estilo para que veas aproximadamente cómo se leerá tu texto en el juego:

- `\n` → salto de línea
- `<EM3>...</EM3>` → encabezado de sección subrayado
- `<EM4>...</EM4>` → énfasis en azul y negrita (normalmente valores de estadísticas)
- `~mission(Name)` → marcador `[Name]` en gris (el juego sustituye el valor real en tiempo de ejecución)

El panel permanece visible en todas las pestañas y refleja la última fila seleccionada en el **Editor de textos**: útil para comprobar el formato de una descripción de misión larga o una entrada de diario antes de aplicar.

## 4. Categorías

Usa el filtro de **Categoría** para centrarte en un dominio:

- **Ships**: nombres y descripciones de naves (`vehicle_Name*`, `vehicle_Desc*`, más las variantes Wikelo/Collector).
- **Ship Items**: escudos, plantas de energía, refrigeradores, motores cuánticos, motores de salto, armas de nave, misiles, bombas, torretas.
- **Missions**: briefings de misión, textos de contratos, descripciones de recompensas.
- **Gear**: armas FPS, armaduras, cascos, trajes, miras.
- **Commodities**: mercancías y materiales de fabricación.
- **Journal**: entradas de diario del juego, estilo Galactapedia.
- **Other**: todo lo demás.

## 5. Búsqueda y filtros

- Usa el **cuadro de búsqueda** para encontrar textos por clave o por contenido.
- Combínalo con los filtros de **Categoría** y **Estado** (Modificado / Mejorado / Sin modificar / Nuevo).
- Marca **Ocultar sin modificar** para ver solo tus propias ediciones.
- Los **cuadros de filtro por columna** bajo cada encabezado afinan la búsqueda dentro de la tabla.
- Haz clic en cualquier encabezado de columna para ordenar. Haz clic en el encabezado **★** para subir los favoritos arriba.

## 6. Naves favoritas

- Haz clic en la columna **★** de cualquier fila de nave para marcarla como favorita. Solo la fila del nombre de una nave puede marcarse como favorita; la fila de descripción de la misma nave no tiene un comportamiento equivalente en el juego, así que las columnas de estrella y de orden quedan vacías ahí.
- Las naves favoritas reciben un prefijo configurable delante del nombre, lo que las sube al principio de la lista de naves del juego.
- Cambia el carácter de prefijo en la pestaña **Mejoras** (por defecto: `*`).
- Marca **Solo nombres de naves y vehículos** en la fila de búsqueda y filtros para reducir la tabla a solo las filas de nombres de naves y vehículos, ocultando las descripciones de naves y el resto de categorías; combínalo con **Solo favoritos** para recorrer exactamente las filas que puedes marcar como favoritas.

## 7. Aplicar los cambios al juego

Haz clic en **Aplicar mejoras** para escribir tus ediciones en la instalación del juego. Antes de sobrescribir nada, se crea una copia de seguridad con fecha y hora del `global.ini` actual en `<carpeta de datos>\<canal>\backups\`.

El color del botón te dice en qué punto estás: **rojo** significa que algo ha cambiado desde tu última aplicación (una edición, una regeneración, un cambio de idioma o de canal) y el juego aún no lo tiene; **verde** significa que el juego ya coincide con lo cargado, y el botón queda desactivado porque no hay nada que rehacer. La misma convención rojo/verde se aplica a **Generar mejoras** y **Aplicar cambios de etiquetas** en la pestaña Mejoras. Si cierras la aplicación con el botón Aplicar todavía en rojo, Smart Citizen te pregunta si aplicar ahora o salir sin aplicar, para que el trabajo sin aplicar nunca se pierda en silencio.

Smart Citizen también estampa una pequeña marca de agua en el texto de versión del lanzador (`Frontend_PU_Version`), añadiendo `\nLocalizations Enhanced with Smart Citizen v{VERSION}` en su propia línea. Así confirmas en el juego que tu loc-pack está activo: mira la etiqueta de versión en el menú principal de Star Citizen. La marca se reescribe con cada aplicación, así que nunca se acumula entre versiones.

## 8. Restaurar una copia de seguridad

Abre el menú **Más** de la barra de herramientas y elige **Restaurar copia** para volver a una versión anterior. Smart Citizen conserva hasta **5 copias de seguridad automáticas**; la más antigua se elimina a medida que se crean nuevas.

## 9. Limpiar la localización

Abre el menú **Más** y elige **Limpiar localización** para borrar el `global.ini` personalizado del directorio del juego y devolver el juego a su texto por defecto (original). Tus cambios guardados en `<carpeta de datos>\<canal>\user.ini` quedan intactos y pueden reaplicarse en cualquier momento.

## 10. Importar un INI

Usa **Importar INI** en la pestaña **Configuración** (también disponible en el menú **Más** de la barra de herramientas) para incorporar un archivo INI existente a tus cambios. Un diálogo de resolución de conflictos te deja decidir, clave por clave: **mantener el actual**, **usar el importado**, **añadir después**, **añadir antes**, o introducir un valor **personalizado**.

## 11. Exportar un Loc-Pack

Abre el menú **Más** y elige **Exportar INI…** para empaquetar el `global.ini` actualmente aplicado en un único zip, `SmartCitizen-LocPack-{canal}-{AAAAMMDD}.zip`, que cualquiera puede soltar en su carpeta `StarCitizen\<canal>\data\Localization\english\` para usar el mismo loc-pack sin instalar Smart Citizen. Útil para compartir configuraciones con amigos o con tu organización.

## 12. Restablecer user.ini

Usa **Restablecer user.ini** en la pestaña **Configuración** para borrar todas tus ediciones personales del canal activo. Una confirmación evita clics accidentales, y antes se guarda automáticamente una copia del `user.ini` actual en `<carpeta de datos>\<canal>\backups\`: el restablecimiento es recuperable si cambias de opinión.

## 13. Exportar / Importar ajustes

Usa **Exportar ajustes…** e **Importar ajustes…** en la pestaña **Configuración** para mover toda tu configuración de Smart Citizen entre PC, o para respaldarla antes de una instalación limpia. La exportación empaqueta tus ajustes de la aplicación y los cambios de `user.ini` de todos los canales en un único zip pequeño, incluida tu ruta de instalación de Star Citizen; las rutas propias de cada máquina que no tendrían sentido en otro PC (tu carpeta de datos, la ubicación de la caché, la geometría de la ventana, los anchos de columna del editor de cadenas) se quedan fuera. La importación superpone esa copia a tu configuración actual y sustituye el `user.ini` de los canales que contiene: tus archivos `user.ini` actuales se guardan antes como instantánea mediante **Restaurar user.ini**, así que una importación es reversible. Tu ruta de Star Citizen solo se conserva si sigue existiendo en el PC donde importas; si no, Smart Citizen la detecta automáticamente. Tras una importación, Smart Citizen se reinicia para cargar la nueva configuración y después ofrece regenerar y aplicar tus mejoras.

## 14. Tras las actualizaciones del juego

Cuando Star Citizen se actualiza, tus ediciones se conservan en `<carpeta de datos>\<canal>\user.ini`. Vuelve a ejecutar **Extraer desde Data.p4k** para obtener los textos originales del juego parcheado: la tabla se recarga automáticamente y tus personalizaciones se reaplican encima.

## 15. Cambiar de idioma

Elige un idioma en el menú **Idioma** de la pestaña **Configuración** (junto a Canal). El cambio afecta tanto a la interfaz de la aplicación como a los textos del juego en la tabla:

- **Inglés** (el predeterminado) usa los textos originales extraídos de tu propio `Data.p4k`.
- **Los demás idiomas** descargan el `global.ini` traducido por la comunidad para ese idioma y lo superponen a la base en inglés: cualquier texto que la traducción no cubra vuelve al inglés en lugar de desaparecer. La descarga se guarda en caché por idioma; volver a un idioma ya usado reutiliza la caché.
- **Las mejoras permanecen en inglés.** Los bloques de estadísticas, etiquetas y detalles de misión se generan a partir de los datos del juego y mantienen su forma en inglés sobre la prosa traducida. Una línea mixta (por ejemplo, un nombre de rol en español dentro de un bloque de estadísticas en inglés) es lo esperado, no un error.
- **Asignar archivo de idioma** (pestaña Configuración) permite apuntar un idioma a otra URL de `global.ini`, por ejemplo tu propio fork de una traducción comunitaria. Tu URL gana sobre la predeterminada incluida.
- Algunos textos de la interfaz solo se actualizan tras reiniciar la aplicación. Los textos de la tabla se recargan de inmediato.

Al aplicar, la aplicación escribe en la carpeta de idioma correspondiente de tu instalación del juego y establece `g_language` en `user.cfg`, para que el juego cargue el archivo correcto.

¿Quieres ayudar a traducir? El estado de las traducciones por idioma se sigue en `languages/TRANSLATIONS.md` del repositorio, y preferimos mil veces tus palabras a las de una máquina. Escríbenos en el Discord.

## 16. Actualizaciones de la aplicación

Smart Citizen comprueba si hay una versión nueva cada vez que arranca. Cuando hay una disponible, las notas de la versión aparecen en una ventana con dos opciones:

- **Actualizar ahora** descarga el nuevo instalador, Windows pide permiso, y Smart Citizen se cierra, se actualiza y se vuelve a abrir en la versión nueva. Tus ediciones, copias de seguridad y configuración quedan intactas.
- **Más tarde** te mantiene en la versión actual; la pregunta volverá en el próximo arranque.

También puedes comprobarlo manualmente en cualquier momento con **Buscar actualizaciones** en la pestaña Configuración. Las versiones portables muestran en su lugar un botón **Abrir página de la versión**, ya que no hay instalador que ejecutar: descarga el zip nuevo y descomprímelo sobre la carpeta antigua.

## Pestaña Mejoras

- Activa superposiciones de estadísticas que añaden datos numéricos a las descripciones: velocidad SCM, PV de escudo, DPS, capacidad de carga, estadísticas de rayo de los láseres de minería (Fractura / Extracción), rendimiento de las herramientas de recuperación de mano, listas de blueprints, XP de misión y más. El XP de misión también indica la vía de reputación que alimenta (ej.: `750 XP (Hauling)`), los contratos de escaneo/minería de Battaglia llevan una etiqueta `[RS ####]` con la firma de recurso base del mineral objetivo, y el diario Mining Compendium lista la RS base de cada mineral junto a sus ubicaciones de minado.
- **Consumibles médicos**: añade una línea de efecto en lenguaje claro a los inyectores CureLife básicos (MedPen, OxyPen, AdrenaPen y compañía), para que la descripción diga lo que hace realmente el inyector en lugar de limitarse a su trasfondo.
- **Mostrar estadísticas encima de la descripción**: coloca el bloque de estadísticas al principio de la descripción en lugar del final, para que los números sean lo primero que leas en el juego.
- **Mostrar Firmas de Recursos (RS) junto a los nombres de minerales**: añade la Firma de Recurso base de cada mineral minable a su propio nombre mostrado (p. ej. «Aluminio (RS 4285)»), para que aparezca en todos los lugares donde el juego muestra ese nombre, incluido el rastreador de misiones. Independiente de la línea Firmas de Recursos de los Campos de detalles de misión de más abajo.
- Activa o desactiva cada categoría de mejoras de forma independiente.
- Configura el carácter de prefijo de las naves favoritas.
- **El seguimiento de blueprints adquiridos** se ha movido a su propia pestaña **Rastreador de blueprints**; consulta la sección siguiente.
- **Creador de etiquetas**: personaliza las etiquetas entre corchetes de los nombres de componentes, misiles, armas de nave y mercancías. Reordena los elementos con ▲/▼, desactiva elementos individuales, cambia la longitud de la abreviatura (`M` / `MIL` / `Military`), elige el separador (ninguno, guion, espacio, etc.) y los corchetes (cuadrados, redondos, ninguno, etc.), y decide si la etiqueta va antes o después del nombre. Los componentes tienen además un elemento **Type** opcional (Escudo, Refrigerador, Planta de energía, etc.), desactivado por defecto. Las mercancías tienen elementos **Label**, **Usage** (a qué se destinan los materiales de fabricación de una mercancía) y **Collection**, todos desactivados por defecto; activa los que quieras desde el Creador de etiquetas. Haz clic en **Aplicar cambios de etiquetas** para guardar y regenerar. (**Generar mejoras** también guarda primero cualquier cambio de etiqueta pendiente, para que un ajuste sin guardar nunca se escape de una regeneración.)
- **Títulos de misión** (pestaña Creador de etiquetas): antepón a los títulos de las misiones de transporte su ruta. Elige la posición (antes, después, o sustituyendo el título), la flecha de la ruta (`>`, `->`, `to`, o las formas `->-`/`->=`/`=>-`/`=>=` que distinguen un punto único de varios en cada extremo), el separador de título, y cuánto detalle mostrar de la ubicación (dirección completa por defecto; el nombre corto puede no mostrarse en misiones raras), con vista previa en vivo. Un transporte se lee entonces `Area18 > Lorville - <título original>`, para ver el trayecto de un vistazo en la lista de contratos, y los transportes con varias paradas listan sus destinos (`Area18 > Lorville, New Babbage`). Dos opciones independientes recortan el título original: **Acortar títulos originales** aplica abreviaciones de frases seleccionadas (p. ej. «Opportunity for Independent Cargo Hauler» → «Intro», «Local Shipment Route» → «Route», más el tratamiento de los prefijos de rango y de la familia Ling), y **Acortar tamaños de carga** abrevia los tamaños («Extra Small» → «XS»). Casillas individuales dan un control más fino — quitar «Cargo» o «Haul», eliminar «Rank», o subrayar los transportes «Direct» para destacarlos — de modo que la ruta y las etiquetas quepan incluso en títulos largos. Las casillas de **Etiquetas generales** de la misma página muestran u ocultan las etiquetas que solo aparecen en el título: la recompensa de reputación, la etiqueta de blueprint, `[ACE]`, la etiqueta `[RS ####]` de Battaglia y el nombre de la vía de reputación. La etiqueta de blueprint se lee `[BP]` cuando todas las versiones de una misión otorgan un blueprint, y `[BP?]` cuando no es seguro (solo algunas versiones lo llevan, o los datos del juego marcan la recompensa como una tirada de azar).
- **Rótulos de misión**: personaliza los encabezados de sección de los bloques de mejora de misión (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), el rótulo de XP mostrado en misiones sin rango de reputación específico (por defecto «Rep»), y la etiqueta de énfasis (EM3 = subrayado, EM4 = color) de los encabezados.
- **Campos de detalles de misión**: muestra u oculta individualmente cada línea del bloque MISSION DETAILS (tipo de misión, dificultad, apariciones, reputación, blueprints, piloto ace y firmas de recursos), para que tus descripciones de misión lleven solo los datos que te importan. **Firmas de Recursos** añade a los contratos de escaneo/minería de Recco Battaglia un desglose que lista la progresión completa del valor RS de cada mineral objetivo, independiente de la etiqueta `[RS ####]` del título de misión y de la anotación en el nombre del mineral de más arriba.
- Haz clic en **Generar mejoras** para extraer los datos de DataForge de `Data.p4k` y reconstruir los archivos INI de mejoras. Los parches declarativos de `patches/` se reaplican de forma idempotente en cada regeneración, para que los errores de datos conocidos de CIG sigan corregidos sin esperar un parche del juego.

## Pestaña Rastreador de blueprints

Lleva el control de qué blueprints de fabricación ya posees, y míralo reflejado en el juego: los objetos adquiridos reciben una etiqueta azul `[Owned]` en las listas POTENTIAL BLUEPRINTS de las misiones, de modo que un contrato te dice de un vistazo qué te queda por conseguir.

- **Dos listas, un transbordo.** Los blueprints disponibles a la izquierda, tu colección a la derecha. Selecciona elementos y muévelos con los botones de flecha. La colección persiste entre sesiones.
- **Encuentra rápido.** Un cuadro de búsqueda filtra ambas listas, y los filtros **Misión / Tipo / Clase / Tamaño / Grado** reducen la lista de disponibles según la misión de origen del blueprint y el tipo de objeto (armadura, munición, arma FPS, objeto de nave, etc.).
- **Escanear registros en busca de blueprints adquiridos** rellena la colección automáticamente: lee los archivos de registro de Star Citizen en busca de los blueprints recibidos en el juego y los marca como adquiridos. Solo se importan los blueprints recibidos desde el último escaneo, así que repetirlo en cualquier momento apenas cuesta. El escaneo necesita que la ruta de instalación de Star Citizen esté configurada en la pestaña Configuración.
- **Analizar también LIVE/HOTFIX (el que no esté activo)** comprueba también el que de esos dos no sea tu canal actual, ya que comparten la misma progresión de cuenta: un blueprint obtenido en LIVE aparece en los registros de HOTFIX y viceversa. Activado por defecto. PTU, EPTU y TECH-PREVIEW son compilaciones de prueba independientes con su propia progresión y nunca se analizan, independientemente de esta opción.
- **Reanalizar todos los registros (ignorar el último análisis)** obliga al siguiente escaneo a releer todas las entradas de registro desde cero, en lugar de solo lo nuevo desde tu último escaneo. Úsalo si tu colección parece incorrecta y un escaneo normal no lo arregla. La casilla se desmarca sola al terminar el escaneo.
- **Exportar blueprints adquiridos… / Importar blueprints adquiridos…** mueven tu colección entre PC, o la comparten con un amigo. La exportación escribe todo lo que posees en un archivo JSON o CSV; la importación lee uno y añade lo que encuentra, sin quitar nunca nada que ya poseas. Las exportaciones de scmdb.net también se importan. El resumen de la importación indica cuántos blueprints eran nuevos y lista los nombres del archivo que Smart Citizen no rastrea.
- **Aplicar etiquetas [Owned]** vuelve a tejer las etiquetas `[Owned]` en tus textos cargados tras cambiar la colección. Como los demás botones de acción, se pone **rojo** cuando tu colección tiene cambios que la tabla aún no ha incorporado y **verde** cuando todo está sincronizado.
- La columna **Adquirido** de la tabla de textos sigue mostrando una estrella y ordenando primero los adquiridos, pero ahora es de solo lectura; la colección se gestiona desde esta pestaña.

## Pestaña Configuración

- **Apariencia**: elige el tema de la aplicación (ver más abajo).
- **Instalación de Star Citizen**: ruta a tu directorio LIVE; detectada automáticamente en la instalación, editable aquí. El menú **Canal** elige qué canal lee y escribe la aplicación, y el menú **Idioma** cambia la aplicación y los textos del juego (ver *Cambiar de idioma* más arriba).
- **Verificar la ubicación**: comprueba que Smart Citizen apunta a la copia de Star Citizen con la que juegas realmente. Si tienes más de una instalación en el PC (una carpeta de biblioteca movida, un segundo disco, restos de una reinstalación), la aplicación puede estar escribiendo justo en la que el lanzador RSI nunca inicia: aplicar informa de éxito, pero en el juego no cambia nada. Este botón busca todas las instalaciones que puede y te dice cuál usa realmente el lanzador, leyendo el registro del propio lanzador en lugar de adivinar por los nombres de las carpetas. Cada instalación encontrada se muestra con sus pruebas, y **Usar esta instalación** redirige Smart Citizen a ella con un clic. Si tu instalación está en un sitio poco habitual, **Analizar todas las unidades** hace una búsqueda más lenta y profunda.
- **Datos de Smart Citizen**: carpeta para `user.ini`, cachés, extracción de DataForge, INI de mejoras generados y copias de seguridad. Por defecto `Documents\Smart Citizen`; sácala de OneDrive si la extracción o la limpieza de caché van lentas.
- **Localización base (extracción P4K)**: haz clic en **Extraer desde Data.p4k** para descomprimir la localización original y los datos de entidades de DataForge directamente desde tu juego instalado. Es la única fuente de los textos base y de los datos de mejoras.
- **Importar INI**: incorpora un archivo INI existente a tus cambios mediante el diálogo de resolución de conflictos.
- **Restablecer user.ini**: borra todas tus ediciones personales del canal activo. Pide confirmación y hace una copia de seguridad automática del `user.ini` actual antes de limpiar.
- **Restaurar user.ini**: devuelve tus ediciones personales a una instantánea anterior. Smart Citizen conserva copias rotativas de `user.ini` (hasta 5, tomadas automáticamente antes de cada cambio): si una importación o edición sale mal, elige una versión anterior y recupera tus textos. La restauración es a su vez reversible: el archivo actual se guarda primero.
- **Exportar ajustes… / Importar ajustes…**: respalda toda tu configuración (ajustes más el `user.ini` de todos los canales) en un único zip pequeño, o restáurala en un PC nuevo. Ver *Exportar / Importar ajustes* más arriba.

## Pestaña Registro

- Registro de la aplicación en tiempo real.
- Filtra por nivel, activa el desplazamiento automático y **exporta** el registro para diagnóstico o informes de errores.

## Temas

Elige un tema en **Configuración → Apariencia**:

- **Predeterminado**: SCLE, un tema ciber azul marino inspirado en la interfaz mobiGlas de Star Citizen.
- **Claro / Oscuro**: temas de interfaz clásicos.
- **ODW**: la firma de Osiris DevWorks, grafito marino con dorado antiguo.

## Disposición de la ventana

Smart Citizen recuerda el tamaño de tu ventana, la disposición del editor de cadenas acoplado y los anchos de tus columnas entre sesiones. Cada pestaña desplaza su propio contenido, así que puedes reducir la ventana todo lo que quieras y llegar a cualquier control desplazándote, en lugar de ver los controles comprimidos o recortados.

Si tu disposición acaba en un estado incómodo (una columna reducida a una franja, o un tamaño de ventana que ya no encaja en tu pantalla), usa **Más → Restablecer las proporciones de la ventana**. Restaura el tamaño de la ventana, la disposición de los paneles y los anchos de columna a sus valores predeterminados. Tus ajustes, tus ediciones y tus datos de localización no se tocan.

## Barra de estado

Muestra el recuento de entradas cargadas / modificadas y el estado de cualquier tarea en segundo plano (extracción, generación, aplicación).

## Visita guiada

Haz clic en el botón **Tutorial** de la barra de herramientas en cualquier momento para repetir la visita guiada: un recorrido paso a paso del flujo de trabajo principal con indicaciones en pantalla señalando cada control. La visita también se ejecuta automáticamente la primera vez que inicias una versión nueva, para que una instalación recién hecha nunca empiece a ciegas. Pulsa **Omitir** en cualquier momento para cerrarla.

## Pestaña FAQ

La pestaña **FAQ** responde a las preguntas que más nos hacen, directamente en la aplicación: qué archivos toca Smart Citizen, si pueden banearte por usarlo, por qué Windows señala el instalador, y cómo deshacer tus cambios. Consúltala primero; si tu pregunta no está cubierta, el Discord está a un clic.

## Atajos de teclado

- **Ctrl+Shift+C**: copiar las filas filtradas al portapapeles (formato clave=valor).

## Solución de problemas

- **Nada en la tabla**: comprueba que **Extraer desde Data.p4k** ha terminado y que la recarga posterior a la extracción ha concluido; después revisa la pestaña **Registro** en busca de errores de lectura.
- **Mejoras vacías o con elementos ausentes**: ejecuta **Generar mejoras** desde la pestaña Mejoras; necesita una caché de DataForge (haz clic antes en **Extraer desde Data.p4k** si aún no lo has hecho).
- **Aplicar mejoras falla**: confirma la ruta de instalación de Star Citizen en la pestaña **Configuración** y que el juego no está en ejecución.
- **Aplicar dice que funcionó pero el juego no cambia**: puede que tengas más de una instalación de Star Citizen y que Smart Citizen apunte a la que no inicias. Pulsa **Verificar la ubicación** en la pestaña **Configuración**: indica la instalación que usa realmente el lanzador RSI y redirige la aplicación con un clic.
- **La extracción dice que Data.p4k está bloqueado**: el lanzador RSI está descargando o verificando una actualización. Espera a que termine (o cierra el lanzador) y vuelve a hacer clic en **Extraer desde Data.p4k**.
- **Datos obsoletos tras una actualización del juego**: vuelve a ejecutar **Extraer desde Data.p4k** y después regenera las mejoras.

## Problemas conocidos

Algunas anomalías de texto tienen su origen en los propios datos de Star Citizen: una referencia errónea de clave de localización en un registro de contrato de CIG, o una recompensa de blueprint cuyos datos no remiten a ningún nombre de visualización real. El juego lee los contratos y las recompensas de blueprint desde su propio `Data.p4k` en tiempo de ejecución, así que Smart Citizen no puede corregir esto en el origen; solo puede corregir el *texto* que genera y aplica. Cuando resulta práctico, sorteamos estos errores a nivel de datos o de generación para que el resultado en el juego se muestre correcto de todos modos.

- **Dosier de Jorrit, «Updated Power Usage Data» muestra el texto de Energy Anomaly**: CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). El contrato `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` de CIG apunta su parámetro `Description` a `@Hockrow_FacilityDelve_P2M1_Repeat_desc` en lugar de a su propio `P2M4_Repeat_desc`, así que los jugadores ven en el juego el texto de ambientación de Energy Anomaly de P2M1 en una misión titulada «Power Usage Data». Smart Citizen lo sortea en dos pasos, ambos declarados en `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. Una edición del XML de DataForge para que nuestro generador de mejoras asocie la lista correcta de blueprints de P2M4 (Corbel Smolder, Geist Rogue/Whiteout) a `P2M4_Repeat_desc` en lugar de reducirla a la de P2M1.
  2. Un arreglo de texto que añade el contenido completo de `P2M4_Repeat_desc` (su texto de ambientación más su propia lista de blueprints) al final de `P2M1_Repeat_desc`, separado por un divisor rotulado. Como el juego lee el puntero defectuoso y consulta `P2M1_Repeat_desc` para ambos contratos, el contrato P2M4 ahora muestra su contenido previsto. Los jugadores de P2M1 ven el bloque de P2M4 como un apéndice rotulado tras su propia descripción: más ruidoso, pero ambos contratos muestran ya la lista de blueprints correcta y el texto de ambientación correcto.

  Cuando CIG corrija STARC-176797, el archivo de parche entero podrá borrarse y la siguiente regeneración volverá a producir descripciones limpias y separadas.

- **Misiones de repostaje que muestran nombres de boquillas corruptos** (p. ej. «Nozzle Fuelgiver Grin Nozzlefast» en lugar de «Norfield») en la lista POTENTIAL BLUEPRINTS de una misión. Las recompensas de blueprint de las boquillas de combustible no remiten a un nombre de entidad resoluble en los datos de CIG como el resto de objetos fabricables, así que nuestro generador de mejoras recurría a una versión «deslugificada» del nombre de archivo interno en lugar del nombre real del producto. Corregido para las 8 variantes de boquilla conocidas (Marlin, Lindstrom, Bendix, Torrez, Ezra, Norfield, Harkin, RN-7s) mediante una corrección de nombres conocidos en `scripts/generate_enhancements_ini.py`; vuelve a ejecutar **Generar mejoras** y **Aplicar al juego** para aplicar la corrección a misiones que ya hayas visto.

## Comentarios, errores y votación de funciones

- **Informa de errores, comparte configuraciones personalizadas y vota las próximas funciones** en el canal de Discord dedicado a Smart Citizen: [Discord de Osiris DevWorks, comentarios y votación #smart-citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) (primero hay que unirse al servidor de Osiris DevWorks: [invitación](https://discord.gg/BNzRegKZ7k)). La priorización de funciones se guía por las reacciones y votos de ese canal: cuanta más demanda tiene una petición, antes llega.
- Al informar de un error, adjunta el registro (pestaña Registro → **Exportar**) y menciona tu versión de Star Citizen, para que podamos distinguir los problemas propios de los cambios del juego.
