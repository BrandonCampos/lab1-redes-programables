# Laboratorio 1 - Redes Programables

## Inventario, Estado y Configuración Segura con Python + SSH

Este proyecto corresponde al Laboratorio 1 del curso Redes Programables.

El programa utiliza Python, Netmiko y SSH para conectarse a equipos de red definidos en un inventario YAML, recolectar información de estado y realizar cambios de configuración de forma idempotente.

## Requisitos

- Linux
- Python 3
- Python venv
- Git
- Netmiko
- PyYAML
- Requests para el extra REST

## Crear entorno virtual

```bash
python3 -m venv env
source env/bin/activate
