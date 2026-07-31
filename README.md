# Consulta Crediticia Guatemala — App Móvil

App web Flask para consultar el análisis crediticio desde cualquier celular Android.

## Estructura del proyecto

```
app_guatemala/
├── app.py              ← Servidor Flask + lógica de datos
├── requirements.txt    ← Dependencias Python
├── Procfile            ← Comando de inicio para Render
├── render.yaml         ← Configuración de Render
└── templates/
    └── index.html      ← Interfaz móvil
```

## Cómo desplegar en Render (paso a paso)

### Paso 1 — Crear cuenta en GitHub
1. Ve a https://github.com
2. Crea una cuenta gratuita si no tienes

### Paso 2 — Subir el código a GitHub
1. Ve a https://github.com/new
2. Crea un repositorio nuevo (ej: `consulta-gt`)
3. Sube los archivos de esta carpeta

### Paso 3 — Crear cuenta en Render
1. Ve a https://render.com
2. Regístrate con tu cuenta de GitHub (es gratis)

### Paso 4 — Desplegar la app
1. En Render, haz clic en "New +" → "Web Service"
2. Conecta tu repositorio de GitHub
3. Render detecta automáticamente el `Procfile`
4. Haz clic en "Create Web Service"
5. Espera ~2 minutos mientras despliega

### Paso 5 — Usar la app
1. Render te da una URL tipo: `https://consulta-gt.onrender.com`
2. Abre esa URL desde tu celular Android en Chrome
3. Ingresa el DPI y consulta

## Uso

- Ingresa el DPI de 13 dígitos
- Presiona "Buscar"
- Ve las 8 secciones del análisis crediticio

## Notas importantes

- El plan gratuito de Render duerme el servidor tras 15 min de inactividad
- La primera consulta después de inactividad tarda ~30-50 segundos
- Las consultas siguientes son inmediatas
- No hay costo mientras uses el plan Free
