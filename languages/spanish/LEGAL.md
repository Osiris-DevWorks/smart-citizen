# Smart Citizen — Legal y cumplimiento

> Esta página es una traducción proporcionada para tu comodidad. En caso de discrepancia, la versión en inglés prevalece.

Esta página reúne en un solo lugar todos los avisos legales, de licencias y de tratamiento de datos de Smart Citizen. Si algo de aquí entra en conflicto con los archivos `LICENSE` o `NOTICE` distribuidos junto al ejecutable, esos archivos prevalecen.

## Reconocimiento de Star Citizen / Cloud Imperium

Smart Citizen es una **herramienta comunitaria no oficial** para Star Citizen. No está desarrollada, respaldada ni patrocinada por Cloud Imperium Games (CIG) ni Roberts Space Industries (RSI), ni afiliada a ellas de ninguna manera. Smart Citizen se acoge a las directrices «Made by the Community» de CIG para contenido y herramientas creados por la comunidad.

**Star Citizen®**, **Roberts Space Industries®** y **Cloud Imperium®** son marcas registradas de Cloud Imperium Rights LLC y Cloud Imperium Rights Ltd. Todos los datos del juego Star Citizen, incluido el contenido de `Data.p4k`, los modelos de naves y componentes, los nombres de objetos, los textos de misión y el trasfondo, son propiedad intelectual de Cloud Imperium Rights LLC.

Smart Citizen no redistribuye ningún contenido de CIG ni de RSI. La aplicación lee archivos de **tu propia instalación con licencia de Star Citizen** en tu equipo local y escribe los textos personalizados por el usuario de vuelta en esa misma instalación. Ningún contenido propiedad de CIG sale de tu ordenador a través de Smart Citizen.

## Licencia de Smart Citizen

Smart Citizen es software de código abierto bajo la **Licencia Apache, versión 2.0**. Puedes obtener una copia de la licencia en [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0). El texto completo de la licencia se distribuye en el archivo `LICENSE` junto al ejecutable, y el código fuente está disponible en el [repositorio de GitHub](https://github.com/Osiris-DevWorks/smart-citizen).

Salvo que la ley aplicable lo exija o se acuerde por escrito, el software distribuido bajo la licencia se distribuye **«TAL CUAL», sin garantías ni condiciones de ningún tipo**, ni expresas ni implícitas. Consulta la licencia para conocer el texto específico que rige los permisos y limitaciones.

## Software de terceros incluido

Smart Citizen incluye el siguiente software de terceros en su instalador. El texto de atribución completo de cada uno está en el archivo `NOTICE` junto al ejecutable.

- **unp4k / unforge**: incluidos en `assets/unp4k/` como `unp4k.exe` y `unforge.exe`. Osiris DevWorks distribuye su propio fork ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) del proyecto original [dolkensp/unp4k](https://github.com/dolkensp/unp4k), con extracción en paralelo y mejoras de rendimiento. Se usan para descomprimir `Data.p4k` y convertir los archivos de entidades de DataForge a XML. Con licencia **MIT**.
- **PyQt6**: framework de interfaz gráfica, de Riverbank Computing. Usado bajo la **GNU General Public License v3 (GPL-3.0)** para distribución no comercial; Riverbank también ofrece licencias comerciales. Smart Citizen es una herramienta comunitaria gratuita y de código abierto y cumple los términos de la GPL-3.0.
- **lxml**: biblioteca de análisis XML, de lxml.de. Usada bajo la licencia **BSD-3-Clause**.

La biblioteca estándar de Python y las demás dependencias de ejecución empaquetadas por PyInstaller llevan sus propias licencias; consulta la Python Software Foundation License en [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Privacidad y tratamiento de datos

Smart Citizen es una **aplicación de escritorio local**. No transmite tus ediciones, tu `user.ini`, tu `base.ini`, tus personalizaciones ni ningún otro contenido de tu equipo a ningún servidor operado por Osiris DevWorks ni por terceros.

### Lo que se queda en tu equipo

Todo. Tus ediciones de localización, copias de seguridad, configuración de la aplicación y caché de DataForge viven exclusivamente en tu disco local:

- **Configuración**: en el Registro de Windows bajo `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` en la instalación estándar, o en `config.json` junto al ejecutable en la versión portable.
- **Ediciones del usuario + copias de seguridad**: `Documents\Smart Citizen\{canal}\` por defecto (configurable en la pestaña Configuración; la versión portable usa `<carpeta-del-exe>\data\` en su lugar).
- **Caché XML de DataForge**: `%LOCALAPPDATA%\Smart Citizen\{canal}\cache\dataforge\`.
- **Volcados de errores + exportaciones manuales del registro**: `Documents\Smart Citizen\logs\` (o el equivalente portable), escritos solo cuando la aplicación falla o cuando haces clic en *Exportar* en la pestaña Registro.

### Lo que sale por la red

Smart Citizen realiza peticiones de red salientes solo en tres circunstancias:

- **Comprobación de actualizaciones**: una pequeña petición sin autenticación a `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` aproximadamente cada 6 horas para comparar la versión instalada con la última publicada en GitHub. Devuelve solo metadatos de la versión (nombre de la etiqueta, URL de la versión); no se envía ningún estado de Smart Citizen.
- **Descargas de idiomas**: al cambiar a un idioma distinto del inglés, Smart Citizen descarga el `global.ini` traducido por la comunidad para ese idioma desde la URL configurada (por defecto el repositorio de GitHub [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization)). La descarga se guarda en caché localmente; no se envía nada desde tu equipo.
- **Fuentes remotas configuradas por el usuario**: si has configurado una fuente de datos apuntando a una URL `http(s)://` en la pestaña Configuración, Smart Citizen consulta esa URL al refrescar los archivos de origen. De fábrica esto solo aplica a la forma de URL «GitHub raw» de la fuente `global`; la configuración estándar desde la v1.0 lee `base.ini` de tu extracción local de Data.p4k.

### Lo que Smart Citizen **no** hace

- Nada de telemetría, analítica ni informes de uso de ningún tipo.
- No se recopila, almacena ni transmite información personal identificable.
- Sin subidas de datos en segundo plano.
- Sin informes de errores automáticos a un servidor remoto: los volcados de errores se escriben **solo localmente** bajo `Documents\Smart Citizen\logs\`. Si quieres compartir uno en un informe de error, copias y pegas el archivo tú mismo.
- Sin cuentas, sin inicio de sesión, sin identidad remota.

Si descubres un comportamiento que contradiga lo anterior, abre un informe de error en [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues).

## Declaración de uso de IA

Partes del código fuente de Smart Citizen se escribieron con la ayuda de **Claude**, el asistente de programación de IA de Anthropic. El código generado es **revisado y aprobado por un mantenedor humano antes de fusionarse**: la IA no hace commits directamente y se trata igual que cualquier otra contribución de código: leída, probada y aceptada solo por sus méritos.

En concreto:

- La asistencia de IA acelera el desarrollo de generadores, clasificadores, refactorizaciones y pruebas; los commits creados con ayuda de IA llevan un sufijo `Co-Authored-By: Claude` en su mensaje, para que el historial sea auditable.
- Toda la lógica de análisis de datos del juego Star Citizen, la clasificación de misiones y las reglas de tratamiento de textos están diseñadas por los mantenedores humanos y validadas contra muestras reales de la caché de DataForge.
- Algunas traducciones de la interfaz y la documentación de Smart Citizen están generadas por IA como marcadores de posición hasta que lleguen traducciones humanas. Se registran, por idioma y por texto, en `languages/TRANSLATIONS.md`, y se sustituyen a medida que llegan traducciones humanas. Las traducciones humanas existentes nunca son modificadas por la IA.
- **La aplicación en sí no contiene ninguna función de IA ni de aprendizaje automático.** Smart Citizen no incluye ningún modelo, no llama a ningún servicio de IA en tiempo de ejecución y no transmite tus ediciones ni los datos del juego Star Citizen a ningún proveedor de IA.

## Comunicar cuestiones legales

Si crees que Smart Citizen infringe un derecho de autor, una marca u otro derecho que te pertenezca — o si tienes una pregunta sobre cómo trata la aplicación tus datos — abre una incidencia o contacta con los mantenedores a través del [Discord de Osiris DevWorks](https://discord.gg/BNzRegKZ7k).
