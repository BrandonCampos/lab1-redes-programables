#!/usr/bin/env python3

import argparse
import json
import os
import re
from datetime import datetime
from getpass import getpass

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning

    requests.packages.urllib3.disable_warnings(
        category=InsecureRequestWarning
    )
except ImportError:
    requests = None


# ============================================================
# COMANDOS POR TIPO DE DISPOSITIVO
# ============================================================

COMANDOS = {
    "mikrotik_routeros": {
        "identidad": "/system identity print",
        "recursos": "/system resource print",
        "interfaces": "/ip address print terse",
        "ruta_default":
            "/ip route print terse where dst-address=0.0.0.0/0",
    },

    # EXTRA MULTIVENDOR
    "cisco_ios": {
        "identidad":
            "show running-config | include hostname",
        "recursos":
            "show version | include uptime",
        "interfaces":
            "show ip interface brief",
        "ruta_default":
            "show ip route 0.0.0.0",
    },
}


# ============================================================
# INVENTARIO
# ============================================================

def cargar_inventario():
    with open(
        "inventario.yaml",
        "r",
        encoding="utf-8",
    ) as archivo:
        datos = yaml.safe_load(archivo)

    return datos["equipos"]


# ============================================================
# CONTRASEÑAS SEGURAS
# ============================================================

def obtener_password(nombre_equipo):
    variable = (
        "LAB_PASS_"
        + nombre_equipo.upper().replace("-", "_")
    )

    password = os.getenv(variable)

    if password:
        return password

    return getpass(
        f"Contraseña para {nombre_equipo}: "
    )


# ============================================================
# PARSERS GENÉRICOS ROUTEROS
# ============================================================

def texto_colon_a_dict(texto):
    datos = {}

    for linea in texto.splitlines():
        linea = linea.strip()

        if ":" in linea:
            clave, valor = linea.split(":", 1)

            datos[clave.strip()] = valor.strip()

    return datos


def parsear_terse(texto):
    registros = []

    for linea in texto.splitlines():
        linea = linea.strip()

        if not linea:
            continue

        registro = {}

        pares = re.findall(
            r'([\w-]+)=("[^"]*"|\S+)',
            linea,
        )

        for clave, valor in pares:
            registro[clave] = valor.strip('"')

        if registro:
            registros.append(registro)

    return registros


# ============================================================
# PARSER CISCO - EXTRA
# ============================================================

def parsear_cisco(
    identidad_texto,
    recursos_texto,
    interfaces_texto,
    ruta_texto,
):
    nombre = "desconocido"

    for linea in identidad_texto.splitlines():
        if linea.strip().startswith("hostname "):
            partes = linea.split()

            if len(partes) >= 2:
                nombre = partes[1]

    uptime = recursos_texto.strip()

    interfaces = []

    lineas = interfaces_texto.splitlines()

    for linea in lineas:
        linea = linea.strip()

        if (
            not linea
            or linea.lower().startswith("interface")
        ):
            continue

        partes = linea.split()

        if len(partes) >= 2:
            nombre_interfaz = partes[0]
            ip = partes[1]

            if ip.lower() == "unassigned":
                ip = None

            interfaces.append(
                {
                    "interface": nombre_interfaz,
                    "address": ip,
                    "network": None,
                }
            )

    gateway = None

    coincidencia = re.search(
        r"(?:via|gateway of last resort is)\s+"
        r"(\d+\.\d+\.\d+\.\d+)",
        ruta_texto,
        re.IGNORECASE,
    )

    if coincidencia:
        gateway = coincidencia.group(1)

    return {
        "nombre": nombre,
        "uptime": uptime,
        "interfaces": interfaces,
        "ruta_default": {
            "dst_address": "0.0.0.0/0"
            if gateway
            else None,
            "gateway": gateway,
            "routing_table": None,
        },
    }


# ============================================================
# ESTADO POR SSH
# ============================================================

def obtener_estado(conexion, device_type):
    comandos = COMANDOS[device_type]

    identidad_texto = conexion.send_command(
        comandos["identidad"]
    )

    recursos_texto = conexion.send_command(
        comandos["recursos"]
    )

    interfaces_texto = conexion.send_command(
        comandos["interfaces"]
    )

    ruta_texto = conexion.send_command(
        comandos["ruta_default"]
    )

    # --------------------------------------------------------
    # MikroTik
    # --------------------------------------------------------

    if device_type == "mikrotik_routeros":

        identidad = texto_colon_a_dict(
            identidad_texto
        )

        recursos = texto_colon_a_dict(
            recursos_texto
        )

        interfaces_crudas = parsear_terse(
            interfaces_texto
        )

        interfaces = []

        for interfaz in interfaces_crudas:
            interfaces.append(
                {
                    "interface":
                        interfaz.get("interface"),

                    "address":
                        interfaz.get("address"),

                    "network":
                        interfaz.get("network"),
                }
            )

        rutas = parsear_terse(
            ruta_texto
        )

        ruta_default = {}

        if rutas:
            ruta_default = {
                "dst_address":
                    rutas[0].get("dst-address"),

                "gateway":
                    rutas[0].get("gateway"),

                "routing_table":
                    rutas[0].get(
                        "routing-table"
                    ),
            }

        return {
            "nombre":
                identidad.get(
                    "name",
                    "desconocido",
                ),

            "uptime":
                recursos.get(
                    "uptime",
                    "desconocido",
                ),

            "interfaces":
                interfaces,

            "ruta_default":
                ruta_default,
        }

    # --------------------------------------------------------
    # Cisco - EXTRA
    # --------------------------------------------------------

    if device_type == "cisco_ios":
        return parsear_cisco(
            identidad_texto,
            recursos_texto,
            interfaces_texto,
            ruta_texto,
        )

    raise ValueError(
        f"device_type no soportado: {device_type}"
    )


# ============================================================
# R6 - CONFIGURACIÓN IDEMPOTENTE
# ============================================================

def asegurar_loopback(
    conexion,
    numero_lista,
    nombre_estudiante,
):
    interfaz = f"lo-ssh-{numero_lista}"

    direccion = (
        f"10.253.0.{numero_lista}/32"
    )

    print("\nR6 - Configuración idempotente")
    print("-" * 45)

    bridge_actual = conexion.send_command(
        f'/interface bridge print terse '
        f'where name="{interfaz}"'
    )

    ip_actual = conexion.send_command(
        f'/ip address print terse '
        f'where interface="{interfaz}"'
    )

    hubo_cambios = False

    # --------------------------------------------------------
    # Crear bridge solo si falta
    # --------------------------------------------------------

    if interfaz not in bridge_actual:

        print(
            f"[CAMBIO] Creando bridge "
            f"{interfaz}"
        )

        conexion.send_command(
            f'/interface bridge add '
            f'name={interfaz} '
            f'comment="{nombre_estudiante}"'
        )

        hubo_cambios = True

    else:
        print(
            f"[OK] Bridge {interfaz} "
            f"ya existe"
        )

    # --------------------------------------------------------
    # Consultar de nuevo antes de agregar IP
    # --------------------------------------------------------

    ip_actual = conexion.send_command(
        f'/ip address print terse '
        f'where interface="{interfaz}"'
    )

    if direccion not in ip_actual:

        print(
            f"[CAMBIO] Agregando "
            f"{direccion}"
        )

        conexion.send_command(
            f'/ip address add '
            f'address={direccion} '
            f'interface={interfaz} '
            f'comment="{nombre_estudiante}"'
        )

        hubo_cambios = True

    else:
        print(
            f"[OK] IP {direccion} "
            f"ya existe"
        )

    if not hubo_cambios:
        print("[OK] Sin cambios")

    # --------------------------------------------------------
    # Verificación posterior
    # --------------------------------------------------------

    print("\nVerificación R6:")

    verificar_bridge = conexion.send_command(
        f'/interface bridge print terse '
        f'where name="{interfaz}"'
    )

    verificar_ip = conexion.send_command(
        f'/ip address print terse '
        f'where interface="{interfaz}"'
    )

    print(verificar_bridge)
    print(verificar_ip)


# ============================================================
# R6 - LIMPIEZA
# ============================================================

def limpiar_loopback(
    conexion,
    numero_lista,
):
    interfaz = f"lo-ssh-{numero_lista}"

    print("\nR6 - Limpieza")
    print("-" * 45)

    ip_actual = conexion.send_command(
        f'/ip address print terse '
        f'where interface="{interfaz}"'
    )

    if ip_actual.strip():

        print(
            f"[LIMPIAR] Eliminando IP "
            f"de {interfaz}"
        )

        conexion.send_command(
            f'/ip address remove '
            f'[find interface="{interfaz}"]'
        )

    else:
        print(
            "[OK] No hay IP que eliminar"
        )

    bridge_actual = conexion.send_command(
        f'/interface bridge print terse '
        f'where name="{interfaz}"'
    )

    if bridge_actual.strip():

        print(
            f"[LIMPIAR] Eliminando "
            f"{interfaz}"
        )

        conexion.send_command(
            f'/interface bridge remove '
            f'[find name="{interfaz}"]'
        )

    else:
        print(
            "[OK] No hay bridge "
            "que eliminar"
        )

    print("[OK] Limpieza finalizada")


# ============================================================
# EXTRA REST
# ============================================================

def obtener_estado_rest(
    equipo,
    password,
):
    if requests is None:
        return {
            "estado": "requests no instalado"
        }

    base_url = (
        f"https://{equipo['host']}/rest"
    )

    autenticacion = (
        equipo["usuario"],
        password,
    )

    try:
        identidad_respuesta = requests.get(
            f"{base_url}/system/identity",
            auth=autenticacion,
            verify=False,
            timeout=10,
        )

        recursos_respuesta = requests.get(
            f"{base_url}/system/resource",
            auth=autenticacion,
            verify=False,
            timeout=10,
        )

        ips_respuesta = requests.get(
            f"{base_url}/ip/address",
            auth=autenticacion,
            verify=False,
            timeout=10,
        )

        rutas_respuesta = requests.get(
            f"{base_url}/ip/route",
            auth=autenticacion,
            verify=False,
            timeout=10,
        )

        identidad_respuesta.raise_for_status()
        recursos_respuesta.raise_for_status()
        ips_respuesta.raise_for_status()
        rutas_respuesta.raise_for_status()

        identidad = identidad_respuesta.json()
        recursos = recursos_respuesta.json()
        ips = ips_respuesta.json()
        rutas = rutas_respuesta.json()

        if isinstance(identidad, list):
            identidad = (
                identidad[0]
                if identidad
                else {}
            )

        if isinstance(recursos, list):
            recursos = (
                recursos[0]
                if recursos
                else {}
            )

        interfaces = []

        for item in ips:
            interfaces.append(
                {
                    "interface":
                        item.get("interface"),

                    "address":
                        item.get("address"),

                    "network":
                        item.get("network"),
                }
            )

        ruta_default = {}

        for ruta in rutas:
            destino = (
                ruta.get("dst-address")
                or ruta.get("dst_address")
            )

            if destino == "0.0.0.0/0":

                ruta_default = {
                    "dst_address":
                        destino,

                    "gateway":
                        ruta.get("gateway"),

                    "routing_table":
                        ruta.get(
                            "routing-table"
                        ),
                }

                break

        return {
            "estado": "ok",

            "datos": {
                "nombre":
                    identidad.get("name"),

                "uptime":
                    recursos.get("uptime"),

                "interfaces":
                    interfaces,

                "ruta_default":
                    ruta_default,
            },
        }

    except Exception as error:

        return {
            "estado":
                f"error REST: {error}"
        }


# ============================================================
# COMPARACIÓN SSH VS REST
# ============================================================

def comparar_ssh_rest(
    estado_ssh,
    estado_rest,
):
    if (
        estado_rest.get("estado")
        != "ok"
    ):
        return {
            "coincide": False,
            "detalle":
                estado_rest.get("estado"),
        }

    datos_rest = estado_rest.get(
        "datos",
        {},
    )

    comparacion = {
        "nombre": (
            estado_ssh.get("nombre")
            == datos_rest.get("nombre")
        ),

        "uptime_disponible": (
            bool(
                estado_ssh.get(
                    "uptime"
                )
            )
            and bool(
                datos_rest.get(
                    "uptime"
                )
            )
        ),

        "cantidad_interfaces": (
            len(
                estado_ssh.get(
                    "interfaces",
                    [],
                )
            )
            == len(
                datos_rest.get(
                    "interfaces",
                    [],
                )
            )
        ),
    }

    comparacion["coincide"] = all(
        comparacion.values()
    )

    return comparacion


# ============================================================
# CONEXIÓN POR NETMIKO
# ============================================================

def conectar_equipo(
    equipo,
    numero_lista,
    nombre_estudiante,
    limpiar=False,
    usar_rest=False,
):
    password = obtener_password(
        equipo["nombre"]
    )

    parametros = {
        "device_type":
            equipo["device_type"],

        "host":
            equipo["host"],

        "username":
            equipo["usuario"],

        "password":
            password,

        "session_log":
            f"logs/{equipo['nombre']}.log",
    }

    resultado = {
        "equipo":
            equipo["nombre"],

        "ip":
            equipo["host"],

        "fecha_hora":
            datetime.now().isoformat(
                timespec="seconds"
            ),

        "estado":
            "error",

        "datos":
            {},
    }

    try:
        with ConnectHandler(
            **parametros
        ) as conexion:

            print(
                f"\n[OK] Conectado a "
                f"{equipo['nombre']}"
            )

            # -----------------------------------------------
            # R4
            # -----------------------------------------------

            estado = obtener_estado(
                conexion,
                equipo["device_type"],
            )

            resultado["estado"] = "ok"
            resultado["datos"] = estado

            print("\nEstado estructurado")
            print("-" * 45)

            print(
                f"Nombre: "
                f"{estado['nombre']}"
            )

            print(
                f"Uptime: "
                f"{estado['uptime']}"
            )

            print("\nInterfaces:")

            for interfaz in estado[
                "interfaces"
            ]:
                print(
                    f"  "
                    f"{interfaz.get('interface')} "
                    f"{interfaz.get('address')}"
                )

            gateway = (
                estado
                .get(
                    "ruta_default",
                    {},
                )
                .get("gateway")
            )

            print(
                "\nGateway por defecto: "
                f"{gateway or '-'}"
            )

            # -----------------------------------------------
            # R6 SOLO PARA ESCRITURA Y MIKROTIK
            # -----------------------------------------------

            if (
                equipo.get("rol")
                == "escritura"
                and equipo["device_type"]
                == "mikrotik_routeros"
            ):

                if limpiar:
                    limpiar_loopback(
                        conexion,
                        numero_lista,
                    )

                else:
                    asegurar_loopback(
                        conexion,
                        numero_lista,
                        nombre_estudiante,
                    )

            # -----------------------------------------------
            # EXTRA REST
            # -----------------------------------------------

            if (
                usar_rest
                and equipo["device_type"]
                == "mikrotik_routeros"
            ):

                print(
                    "\n[EXTRA] Consultando REST..."
                )

                estado_rest = (
                    obtener_estado_rest(
                        equipo,
                        password,
                    )
                )

                resultado[
                    "estado_rest"
                ] = estado_rest

                comparacion = (
                    comparar_ssh_rest(
                        estado,
                        estado_rest,
                    )
                )

                resultado[
                    "comparacion_ssh_rest"
                ] = comparacion

                print(
                    "[EXTRA] Comparación "
                    "SSH vs REST:"
                )

                print(
                    json.dumps(
                        comparacion,
                        indent=4,
                        ensure_ascii=False,
                    )
                )

    except NetmikoAuthenticationException:

        mensaje = (
            "error de autenticacion"
        )

        print(
            f"[ERROR] "
            f"{equipo['nombre']}: "
            f"{mensaje}"
        )

        resultado["estado"] = mensaje

    except NetmikoTimeoutException:

        mensaje = (
            "error de conexion"
        )

        print(
            f"[ERROR] "
            f"{equipo['nombre']}: "
            f"{mensaje}"
        )

        resultado["estado"] = mensaje

    except Exception as error:

        mensaje = str(error)

        print(
            f"[ERROR] "
            f"{equipo['nombre']}: "
            f"{mensaje}"
        )

        resultado["estado"] = mensaje

    return resultado


# ============================================================
# TABLA RESUMEN
# ============================================================

def imprimir_resumen(reporte):
    print("\nRESUMEN")
    print("-" * 90)

    print(
        f"{'EQUIPO':<18}"
        f"{'IP':<18}"
        f"{'ESTADO':<22}"
        f"{'INTERFACES':<15}"
        f"{'GATEWAY':<17}"
    )

    print("-" * 90)

    for item in reporte:

        datos = item.get(
            "datos",
            {},
        )

        interfaces = datos.get(
            "interfaces",
            [],
        )

        cantidad_interfaces = len(
            interfaces
        )

        ruta = datos.get(
            "ruta_default",
            {},
        )

        gateway = (
            ruta.get("gateway")
            if ruta
            else None
        )

        print(
            f"{item['equipo']:<18}"
            f"{item['ip']:<18}"
            f"{item['estado']:<22}"
            f"{cantidad_interfaces:<15}"
            f"{gateway or '-':<17}"
        )


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Laboratorio 1 - "
            "Inventario y configuración "
            "con Netmiko"
        )
    )

    parser.add_argument(
        "--numero-lista",
        type=int,
        required=True,
        help=(
            "Número de lista del estudiante"
        ),
    )

    parser.add_argument(
        "--nombre",
        default="Brandon",
        help=(
            "Nombre para comentarios "
            "en RouterOS"
        ),
    )

    parser.add_argument(
        "--limpiar",
        action="store_true",
        help=(
            "Elimina solamente los objetos "
            "creados por este estudiante"
        ),
    )

    parser.add_argument(
        "--rest",
        action="store_true",
        help=(
            "Ejecuta también el extra REST "
            "del MikroTik"
        ),
    )

    args = parser.parse_args()

    equipos = cargar_inventario()

    reporte = []

    for equipo in equipos:

        resultado = conectar_equipo(
            equipo=equipo,
            numero_lista=args.numero_lista,
            nombre_estudiante=args.nombre,
            limpiar=args.limpiar,
            usar_rest=args.rest,
        )

        reporte.append(resultado)

    with open(
        "reporte_estado.json",
        "w",
        encoding="utf-8",
    ) as archivo:

        json.dump(
            reporte,
            archivo,
            indent=4,
            ensure_ascii=False,
        )

    print(
        "\nReporte guardado "
        "en reporte_estado.json"
    )

    imprimir_resumen(reporte)


if __name__ == "__main__":
    main()
