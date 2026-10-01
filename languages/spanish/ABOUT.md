# Smart Citizen

*Smarter Strings for Star Citizen*

> Esta página es una traducción proporcionada para tu comodidad. En caso de discrepancia, la versión en inglés prevalece.

## Acerca de este proyecto

**Smart Citizen** es una herramienta potente y fácil de usar para que los jugadores de Star Citizen personalicen los textos de localización de su juego. Carga, edita y aplica cambios de localización con persistencia completa, copias de seguridad automáticas y compatibilidad transparente con las actualizaciones del juego.

Desarrollado por **Osiris DevWorks**, un estudio unipersonal dedicado a crear herramientas útiles para la comunidad de jugadores.

## La promesa de Osiris DevWorks

Todas las herramientas de Osiris DevWorks serán **completamente gratuitas** o tendrán un **nivel gratuito**. Creemos en crear valor para los jugadores sin muros de pago ni suscripciones obligatorias.

## Equipo ODW

- **Osiris_x**
- **Tichro**

## Colaboradores

Gracias a quienes han contribuido con código a Smart Citizen:

- **Stealrull**
- **Ishikudeska**
- **jonigirl**
- **Coerwyn**
- **denis-coach** (h0use)
- **scubamount**
- **hkstrongside**
- **odw-okano**

## Traductores

Gracias a quienes han traducido la interfaz de Smart Citizen:

- **Akwa** (Français)
- **Nxzzin** (Português brasileiro)
- **Thord82** (Español)

## Agradecimientos

Gracias a los testers que ayudaron a dar forma a Smart Citizen con sus comentarios:

- **Boogie Man**
- **Perseuscz**
- **Flat Earth**
- **Lord Valium**
- **Zero**
- **Apolleon Phoibos**
- **Epiq**
- **Narull**
- **XaileiShiv**
- **Mindbulletz**

### Patrocinadores

Gracias a quienes han apoyado el proyecto económicamente: vuestras aportaciones ayudan a mantener Smart Citizen gratuito para todo el mundo:

- **Dimwit the Wise**

Smart Citizen también incluye herramientas de terceros:

- [**Osiris-DevWorks/odw-fast-unp4k**](https://github.com/Osiris-DevWorks/odw-fast-unp4k): `unp4k.exe` y `unforge.exe`, usados para descomprimir `Data.p4k` y convertir DataForge a XML. Es nuestro fork del proyecto original [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k), con extracción en paralelo y otras mejoras de rendimiento.

Los textos del juego en idiomas distintos del inglés son traducciones comunitarias:

- [**Dymerz/StarCitizen-Localization**](https://github.com/Dymerz/StarCitizen-Localization): las traducciones comunitarias de `global.ini` que alimentan las opciones de idioma francés, portugués de Brasil, italiano y turco. Sus traductores hacen aquí el verdadero trabajo; nosotros solo lo entregamos.
- [**Thord82/Star_citizen_ES**](https://github.com/Thord82/Star_citizen_ES): la traducción comunitaria de `global.ini` que alimenta la opción de idioma español.
- [**stdblue/StarCitizenJapaneseResources**](https://github.com/stdblue/StarCitizenJapaneseResources): la traducción comunitaria de `global.ini` que alimenta la opción de idioma japonés.
- [**42Kit**](https://ini.42kit.com/): la traducción comunitaria de `global.ini` que alimenta la opción de idioma chino.
- [**rjcncpt/StarCitizen-Deutsch-INI**](https://github.com/rjcncpt/StarCitizen-Deutsch-INI): la traducción comunitaria de `global.ini` que alimenta la opción de idioma alemán.

## Funciones principales

### 🎯 Funciones básicas
- **Cargar y editar**: carga el `global.ini` de tu instalación de Star Citizen y personaliza los textos en una vista de tabla intuitiva
- **Multi-canal**: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW tienen cada uno su propio `user.ini`, caché, copias de seguridad y extracción de DataForge aislados; cambia de canal desde la pestaña Configuración sin reiniciar
- **Multi-idioma**: alterna la aplicación y los textos del juego entre inglés, francés, español, portugués de Brasil, japonés, chino, italiano, alemán y turco desde la pestaña Configuración. Los idiomas distintos del inglés superponen un `global.ini` traducido por la comunidad a la base en inglés, con retorno al inglés para lo no traducido. Se irán exponiendo más idiomas a medida que lleguen traducciones comunitarias (ver `languages/TRANSLATIONS.md`)
- **Contratos de misión**: edita los textos de contratos y briefings desde la categoría Missions dedicada
- **Filtrado inteligente**: busca textos, filtra por categoría (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other) o por estado de modificación
- **Filtros por columna**: escribe directamente en los cuadros de filtro bajo cada encabezado de columna para búsquedas precisas
- **Vista previa en vivo**: un panel lateral muestra el texto de la fila seleccionada con los tokens de localización del juego (saltos de línea, énfasis EM3/EM4, marcadores de misión) convertidos a HTML con estilo, para ver aproximadamente cómo se leerá el texto en el juego
- **Panel editor lateral**: un lienzo activable desde la barra de herramientas, redimensionable y desacoplable, para editar valores largos (entradas de diario, briefings de misión, descripciones de naves) con botones Subrayar/Resaltar y sincronización en vivo entre paneles
- **Aplicación segura**: la aplicación escribe en `global.ini` con una copia de seguridad automática previa con fecha y hora, valida el resultado contra el conjunto de claves original y revierte automáticamente ante cualquier discrepancia
- **Restauración de copias**: conserva hasta 5 versiones de copia de seguridad por canal; revierte los cambios en cualquier momento con un clic
- **Limpiar localización**: devuelve el juego a su texto original sin perder tus cambios guardados
- **Importar INI**: importa un archivo INI existente y resuelve los conflictos clave por clave con el diálogo integrado
- **Modo simple y modo avanzado**: abre en una pantalla simple de dos botones (uno aplica las mejoras con tu configuración guardada, el otro cambia al avanzado), o usa la interfaz avanzada completa (tabla, filtros, Mejoras, Configuración) siempre que quieras editar a mano. Elige el predeterminado en la instalación y alterna dentro de la aplicación
- **Pestaña FAQ**: las preguntas que más recibimos, respondidas directamente en la aplicación — qué archivos se tocan, el riesgo de baneo, el aviso de aplicación no reconocida de Windows, y cómo deshacer los cambios
- **Ventana y columnas flexibles**: cambia el tamaño de la ventana a tu gusto — cada pestaña desplaza su propio contenido en lugar de comprimir o recortar los controles. Las columnas del Editor de textos se redimensionan arrastrando (doble clic en un separador para ajustarla a su contenido) y tus anchos y la disposición de la ventana se conservan entre inicios, con **Más → Restablecer las proporciones de la ventana** para volver a los valores predeterminados
- **Tutorial guiado**: una visita con indicaciones acompaña a los nuevos usuarios por el flujo de trabajo en el primer arranque de cada versión, repetible en cualquier momento desde el botón Tutorial

### 🔄 Origen de datos y persistencia
- **Origen: Data.p4k**: toda la localización original y los datos de entidades de DataForge se descomprimen directamente desde tu `Data.p4k` instalado; sin descargas, sin réplicas comunitarias, siempre en sintonía con tu versión real del juego
- **Ediciones persistentes**: tus personalizaciones se guardan automáticamente y se recargan en cada sesión
- **Migración transparente**: cuando Star Citizen se actualiza, vuelve a extraer del `Data.p4k` parcheado; tus ediciones guardadas se reaplican automáticamente sobre los nuevos textos base
- **Interfaz cuidada**: tabla de alto rendimiento con filtros, edición en línea, atajos de teclado y una interfaz moderna

### 📊 Mejoras
- **Estadísticas de naves**: velocidad SCM, combustible de hidrógeno/cuántico, capacidad de carga, armamento completo y multiplicadores de blindaje (físico / energético / distorsión / térmico) añadidos a las descripciones de naves
- **Estadísticas de componentes**: PV de escudo, consumo de energía, tasa de refrigeración, regeneración y similares para escudos, refrigeradores, plantas de energía, motores cuánticos y radares, con etiquetas de nombre estilo `[MIL-S2-A]` por defecto (totalmente personalizables en el Creador de etiquetas)
- **Estadísticas de armas**: DPS, cadencia, alcance y daño de cañones y torretas de nave, de S1 a capital. Las armas de nave reciben una etiqueta daño+tamaño estilo `[E-S2]`, los misiles `[IR-S1] Arrester III` y las bombas `[S5] 500SCB Cluster`
- **Anotaciones de misión**: etiquetas de recompensa de blueprint `[BP]` / `[BP?]` en los títulos, más bloques estructurados *MISSION DETAILS*, *POTENTIAL BLUEPRINTS* e *ITEM REWARDS* en las descripciones. Las líneas de nivel de reputación muestran nombres reales de rangos (Rookie, Jr. Contractor, etc.) en lugar de numeración genérica. El XP de misión indica la vía de reputación que alimenta, y los títulos de escaneo/minería de Battaglia llevan etiquetas de firma de recurso `[RS ####]`, acompañadas por un desglose «Resource Signatures» en MISSION DETAILS por cada mineral objetivo y una anotación en el nombre del mineral que aparece en todos los lugares donde el juego muestra ese nombre, incluido el rastreador de misiones (dos opciones independientes, ambas activadas por defecto)
- **Referencias cruzadas del diario**: las entradas del Mining Compendium reciben referencias de fabricación y la firma de recurso base de cada mineral; las mercancías usadas en fabricación reciben una etiqueta de nombre `[CF]` personalizable y la lista de todos los blueprints que las requieren
- **Efectos de consumibles médicos**: los inyectores CureLife básicos (MedPen, OxyPen, AdrenaPen y compañía) reciben una línea de efecto en lenguaje claro, para que la descripción diga lo que hace el inyector en lugar de limitarse a su trasfondo
- **Naves favoritas**: marca una nave con estrella para anteponer un prefijo configurable (por defecto `*`) a su nombre y subirla al principio del terminal ASOP del juego
- **Creador de etiquetas**: personaliza las etiquetas entre corchetes de componentes, misiles, armas de nave y mercancías; reordena los elementos, cambia la longitud de la abreviatura (M / MIL / Military), elige separadores y corchetes, o coloca la etiqueta después del nombre. Los componentes tienen un elemento Type opcional (Escudo, Refrigerador, etc.); las mercancías tienen un elemento Usage que muestra a qué se destinan sus materiales de fabricación
- **Títulos de misión**: antepón a los títulos de transporte su ruta (p. ej. `Area18 > Lorville`) — posición, flecha, separador y detalle de la ubicación configurables, más un acortado opcional de los títulos originales, con vista previa en vivo
- **Estadísticas arriba o abajo**: elige si el bloque de estadísticas va al principio o al final de la descripción
- **Rastreador de blueprints**: una pestaña dedicada para marcar los blueprints de fabricación que ya posees. Mueve elementos entre Disponibles y Adquiridos, filtra por Misión / Tipo / Clase / Tamaño / Grado, y los objetos adquiridos reciben una etiqueta azul `[Owned]` en las listas de blueprints de las misiones. **Escanear registros en busca de blueprints adquiridos** rellena la colección automáticamente desde tus archivos de registro de Star Citizen, importando solo lo nuevo desde el último escaneo, y **Exportar / Importar blueprints adquiridos** mueve la colección entre PC (JSON o CSV; la importación solo añade, y las exportaciones de scmdb.net también funcionan)
- **Rótulos de misión**: renombra los encabezados de sección (MISSION DETAILS, POTENTIAL BLUEPRINTS, etc.), el rótulo de XP y la etiqueta de énfasis de los encabezados
- **Parches declarativos para errores de datos de CIG**: un sistema de parches aplica correcciones a los errores conocidos de DataForge en el momento de la extracción, para que el texto del juego se lea correctamente sin esperar a CIG
- **Categorías selectivas**: activa o desactiva cada categoría de mejoras de forma independiente desde la pestaña Mejoras

### 🎨 Temas
- **Predeterminado**: tema ciber azul marino inspirado en la interfaz mobiGlas de Star Citizen
- **Claro / Oscuro**: temas de interfaz clásicos
- **ODW**: el tema insignia de Osiris DevWorks, grafito marino con dorado antiguo

### 🛡️ Gestión de datos
- **Copias de seguridad automáticas**: copias con fecha y hora creadas antes de cada aplicación al juego (hasta 5 por canal)
- **Persistencia en el registro**: todas las rutas y preferencias se guardan de forma segura en el Registro de Windows
- **Almacenamiento configurable**: tus ediciones se guardan bajo `<carpeta de datos>\<canal>\` (por defecto `Documents\Smart Citizen`, un subárbol aislado por canal de Star Citizen) para una persistencia segura entre sesiones
- **Copia de seguridad de ajustes**: exporta toda tu configuración (preferencias, configuraciones de etiquetas y los cambios de textos de todos los canales) a un único zip pequeño, e impórtalo después en un PC nuevo o tras descomprimir una versión portable limpia. Las importaciones guardan primero una instantánea de tus archivos actuales, así que son reversibles
- **Registro integrado**: registro de la aplicación en tiempo real con filtro de nivel, desplazamiento automático y botón de exportación para informes de errores
- **Actualizador automático**: Smart Citizen consulta las versiones de GitHub al arrancar y muestra las notas de la versión en la aplicación; un clic (más un permiso de Windows) descarga la actualización, la instala y reabre la aplicación

## Inicio rápido

1. **Primer arranque**: la aplicación detecta automáticamente tu instalación de Star Citizen (editable en la pestaña **Configuración**)
2. **Extraer**: haz clic en **Extraer desde Data.p4k** en la pestaña Configuración para descomprimir la localización original y los datos de entidades de DataForge desde tu juego instalado; los textos se cargan automáticamente en la tabla al terminar la extracción
3. **Editar textos**: usa la búsqueda y los filtros, y haz doble clic en cualquier celda de Valor personalizado para personalizar el texto
4. **Aplicar**: haz clic en **Aplicar mejoras**; tus cambios se guardan y se aplican con una copia de seguridad automática
5. **Mejoras (opcional)**: abre la pestaña Mejoras para activar las superposiciones de estadísticas de naves, componentes, armas y recompensas de misión
6. **Tras las actualizaciones del juego**: vuelve a ejecutar Extraer desde Data.p4k; tus ediciones se reaplican automáticamente

## Comunidad y soporte

### Únete
- 💬 [Comunidad de Discord](https://discord.gg/BNzRegKZ7k): obtén ayuda, comparte configuraciones, pide funciones
- 🐛 [Comentarios, errores y votación de funciones de Smart Citizen](https://discord.com/channels/1438175448420057323/1472394204347895890): canal dedicado a informes de errores, comentarios y votación de las próximas funciones (únete antes al servidor con la invitación de arriba)

### Guías en vídeo
- 🎥 [Star Citizen Hides Important Mission Info – This Tool Shows It In-Game & More!](https://www.youtube.com/watch?v=Xo1t404gsgs) por **Karolinger**: una presentación de la comunidad sobre las funciones de Smart Citizen

### Apoya este proyecto
Smart Citizen es completamente gratuito. Si te resulta útil:
- 💳 [Donar por PayPal](https://www.paypal.com/ncp/payment/YAWXHMGZH8T76)
- 💰 [Donar por Venmo](https://venmo.com/u/Amr-Abouelleil)

## Otras herramientas de Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)**: gestiona y comparte tus configuraciones de hangar de Star Citizen
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)**: importa, edita y exporta tus perfiles de controles de Star Citizen
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)**: herramienta AFK para evitar desconexiones por inactividad

## Construido con

Construido con **PyQt6** e inspirado en el trabajo de localización de la comunidad de Star Citizen.

**GitHub**: https://github.com/Osiris-DevWorks/smart-citizen

## Licencia y avisos legales

Smart Citizen está licenciado bajo la **Licencia Apache, versión 2.0**.

Consulta la pestaña **Legal** para el resumen completo de la licencia, las atribuciones del software de terceros incluido (unp4k / PyQt6 / lxml), los avisos «Made by the Community» de Cloud Imperium, la declaración de privacidad y gestión de datos, y la declaración de uso de IA.
