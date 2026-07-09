# polizas/management/commands/cruzar_asegurados_amca.py
"""
Cruza la lista de asegurados AMCA (la planilla de Franco) contra las
polizas ya cargadas en Thames, comparando por PATENTE.

Distingue 3 casos por patente:
  1) Existe una poliza de compania AMCA          -> OK
  2) La patente existe pero con OTRA compania    -> falta cargar la de AMCA
  3) La patente no existe en Thames               -> no cargada

NO MODIFICA NADA. Solo lee y muestra un reporte en pantalla.

USO:
    python manage.py cruzar_asegurados_amca
    (o en Railway: railway run python manage.py cruzar_asegurados_amca)
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum
from polizas.models import Poliza

CLIENTES_AMCA = [
    ("JORGE DANIEL", "LOPEZ", "JPU922"),
    ("SERGIO DANIEL", "CABALLERO", "AA406HE"),
    ("RUBEN ALEJANDRO", "GUZMAN", "JFT020"),
    ("JORGE RICARDO", "ROJAS", "AD454CS"),
    ("FABIOLA JUDITH", "GONZALEZ", "AE330PU"),
    ("MONICA PATRICIA", "PERASSO", "PQB195"),
    ("MIGUEL ÁNGEL", "RECALDE", "OUK372"),
    ("PACHECO LEZCANO", "GERMAN", "KIZ825"),
    ("JORGE TRISTAN", "CABRERO", "OYN926"),
    ("LAURA MERCEDES", "TONIETTI", "KSY974"),
    ("BENITEZ BRUNO", "CRISTINO", "FMJ341"),
    ("HUGO", "RETAMOZO", "ICY762"),
    ("ADELA", "TORRICO", "AD068IT"),
    ("DANIEL", "ESTEBAN", "FCI397"),
    ("DIAZ", "CORREA", "FOX556"),
    ("ROA", "AURELIO", "AB658TH"),
    ("MALE GUENDIRENA", "HENRY", "AD865MT"),
    ("SAAVEDRA", "JOSE ANTONIO", "AC290ML"),
    ("AYALA", "NICOLE AGUSTINA", "MYG945"),
    ("MARCOS RAMON", "MARTINEZ", "HJA311"),
    ("ROMINA GISELA", "MACEDO", "DHU679"),
    ("DARIO ALEJANDRO", "ARGAÑARAZ", "OCH312"),
    ("ORTZ", "CAYETANO ROQUE", "LFD065"),
    ("JOSE ALBERTO", "ALVESS", "OQE583"),
    ("DA SILVA", "LUIS IGNACIO", "EJJ680"),
    ("GUSTAVO JAVIER", "CABRERA", "JYR689"),
    ("ALEJANDRO GERMAN", "GIMENEZ", "EDB054"),
    ("DYLAN SEBASTIAN", "RAMIREZ SANCHEZ", "JDG206"),
    ("BALLES", "DARIO", "NHM878"),
    ("JORGE", "WALDEMAR GOMEZ", "FKA956"),
    ("ORQUIOLA MIÑO", "NESTOR JAVIER", "ETG808"),
    ("MARIA ALEJANDRA", "ALCAMI", "HCB691"),
    ("CLAUDIO GUILLERMO", "LARA", "DNA856"),
    ("ANTONIO", "CARDOZO", "FCU803"),
    ("WALDEMIRO MIGUEL", "KOTILO", "EWK722"),
    ("AARON NAHUEL", "BOGADO", "GBW987"),
    ("CESAR DAMIAN", "ABREGU", "FVM651"),
    ("ALEJANDRO MARTIN", "LESCANO", "MPY646"),
    ("FEDERICO JESUS", "QUINTANA", "EGU377"),
    ("FABRICIO HERNAN", "GAMBATTI", "ONM094"),
    ("CABRERA", "HENRY", "HEJ148"),
    ("LUGO", "BRIAN", "HMP974"),
    ("ENRIQUE EZEQUIEL", "GORJON", "CHM358"),
    ("VERONICA NOEMI", "BARBOSA", "FOH263"),
    ("SANDRA MARICEL", "RODRIGUEZ", "FDT601"),
    ("JULIO IGNACIO", "ROQUE", "JRN983"),
    ("ELBIO OMAR", "FRANCO MARTINEZ", "MID055"),
    ("SEBASTIAN DIEGO", "VERON", "EPM604"),
    ("JULIAN", "GONZALEZ", "AB216YB"),
    ("MAXIMILIANO", "MERNES", "PKT198"),
    ("DIEGO DANIEL", "FRAGATA", "EZV474"),
    ("SHEILA MACARENA", "GUTIERREZ", "FHI013"),
    ("CARLOS ALBERTO", "BIROCCIO", "HNE056"),
    ("SABRINA MAYRA", "BAEZ", "CSV608"),
    ("JORGE ALEJANDRO", "GIGENA", "GFH665"),
    ("MORENO", "JORGE LUIS", "DGU214"),
    ("ROMAN DE ALVARENGA JUSTA", "ERICA", "DED608"),
    ("LEANDRO ARIEL", "GALVAN", "FKS179"),
    ("ANDRES OSCAR", "DANNIBALE", "CTK102"),
    ("MARIELA LOURDES", "LABONIA", "JBO825"),
    ("ROBERTO OMAR", "LAMBERTUCCI", "EQS619"),
    ("MIGUEL ANGEL", "PAZ", "GGD895"),
    ("GABRIEL ALEJANDRO", "ARANDA", "GZO617"),
    ("CLAUDIO ROMAN", "BASUALDO", "GPP955"),
    ("JESICA DIANA", "BALDIVIESO", "JQK145"),
    ("ARMOA MARTIN", "LEIVA", "DSY101"),
    ("JUAN CARLOS", "ACOSTA GONZALEZ", "IMI767"),
    ("FERNANDO MARTIN", "AGUIRRE", "GAH975"),
    ("WALTER", "CHAMORRO AQUINO", "IQD716"),
    ("JOSE MARIA", "PEREZ", "AZC165"),
    ("ELBIO", "MORAES", "IOP496"),
    ("MAXIMILIANO AGUSTIN", "CARRANZA", "KRT124"),
    ("OSVALDO", "DANIEL ROA", "DYR518"),
    ("JOAQUIN ELIAS", "STAZIONE RIVERO", "EFM107"),
    ("GASTON EZEQUIEL", "RIVAS", "MGE325"),
    ("SERGIO ALEJANDRO", "OLMEDO", "BNI404"),
    ("NICOLAS FACUNDO", "GOMEZ", "GUK256"),
    ("JUAN PEDRO", "DOMINGUEZ", "EIY967"),
    ("AMADO", "RUIZ", "KDE907"),
    ("LUIS ALBERTO", "GIMENEZ CANDIA", "EOE481"),
    ("ARIAN", "CORONEL", "HGI453"),
    ("SERGIO JAVIER", "JARA", "AB984BS"),
    ("CRISTIAN MARCELO", "MALDONADO", "PDA332"),
    ("ANGEL  ISAIAS", "TRILLO CAMPOS", "PIH735"),
    ("JUAN CARLOS", "ESCOBAR ROFRIGUEZ", "EIG562"),
    ("HECTOR GABRIEL", "BENTANCOURT", "DDO553"),
    ("HERBES", "CHAVEZ", "CVA776"),
    ("RICARDO ANDRES", "PITA", "AA196EH"),
    ("MAURO GERMAN", "CORBANI", "OUX960"),
    ("ENRIQUE ARIEL", "BRITOS", "GLN498"),
    ("NESTOR BORGE", "IGNACIO", "FBP851"),
    ("ANIBAL RAMON", "RODAS", "JPU446"),
    ("SAYDA OLENKA", "ORDAYA MASGO", "GRD853"),
    ("LUIS", "GUCHA", "GRW375"),
    ("HECTOR", "CORONEL", "IIS517"),
    ("HECTOR ANGEL", "SCARFO", "JKH648"),
    ("CRISTIAN LEONARDO", "LOPEZ", "IGW702"),
    ("SUSANA", "BELIZAN", "AC348QU"),
    ("PABLO", "SALINAS", "AB950SU"),
    ("MARIA", "MARTINEZ", "KLK"),
    ("RUBEN", "IBAÑEZ", "DKI123"),
    ("VALERIA", "GALVAN", "EJX616"),
    ("THOMAS", "SARTO", "AA644DF"),
    ("LORENA ROXANA", "CASCO", "KZU454"),
    ("BRIGIDO CATALINO", "LEGUIZA", "DJZ930"),
    ("EMANUEL ANTONIO", "CABRERA", "FZQ217"),
    ("GUSTAVO ANDRES", "GALLARDO", "HQQ299"),
    ("MAFALDA BEATRIZ", "RODRIGUEZ", "FNA058"),
    ("JORGE", "MARTINEZ", "PPY434"),
    ("SOLEDAD", "ROMINA", "MHV000"),
    ("CELSON", "ALIENDE", "FPD344"),
    ("CLAUDIO LEANDRO", "MARTINEZ", "ENZ155"),
    ("NORBERTO RENE", "ALVAREZ", "GGM992"),
    ("ANGELICA", "MORALES", "FDQ961"),
    ("PEREZ", "LIDIA", "CKH073"),
    ("MARCELO", "VICARIO", "AB879QD"),
    ("MARIA LAURA", "VERRI", "HWG977"),
    ("CRISTIAN DIEGO", "GOGLIO", "EFL629"),
    ("OSCAR IVAN", "ALDANA", "MYA338"),
    ("ANGEL CUSTODIO", "FERNANDEZ", "EEX988"),
    ("EDGAR EMILIANO", "SALFO", "GKW928"),
    ("JUAN", "AGUIRRE", "MYB804"),
    ("DANIEL", "CEJAS", "EXR220"),
    ("DIEGO", "ORUE", "GPA392"),
    ("KARINA", "RIOS", "FJM955"),
    ("JONATHAN SEBASTIAN", "GONZALEZ", "IFR143"),
    ("JUAN", "RAMIREZ", "HAR821"),
    ("HUMBERTO", "CONDORI", "AC673OR"),
    ("FRANCO", "PALAVECINO", "FAD913"),
    ("MARCELO", "ALCALDE", "AA680HG"),
    ("ELIAS", "PORTILLO", "HCM429"),
    ("MIRANDA", "MATIAS", "HSK760"),
    ("HECTOR RUBEN", "MORINICO", "EBT969"),
    ("ADELA", "TORRICO LOPEZ", "AD038JT"),
    ("CESAR DAMIAN", "ABREGU", "FVM351"),
    ("ENRIQUE FERNANDO", "PORRO", "AVJ183"),
    ("", "", "HLB312"),
    ("", "", "FPB851"),
    ("", "", "KLK140"),
    ("", "", "GCI841"),
    ("", "", "KCE734"),
    ("", "", "FUF590"),
    ("", "", "MFF712"),
    ("", "", "EYT864"),
    ("DANIELA ALEJANDRA", "RODRIGUES CORREIA", "JLI057"),
    ("", "", "EIB341"),
    ("LORENZO HUGO", "ALBERTO", "IFK889"),
    ("SEBASTIAN", "DOMINGUEZ", "ENZ998"),
    ("CRISTIAN", "PAZ", "NEO084"),
    ("WALTER", "ALVESS", "EYQ590"),
    ("BRIAN GABRIEL", "BAZAN", "FPM784"),
    ("JOSE ALBERTO", "ALMARAZ", "OQO265"),
    ("JOSE ALEJANDRO", "VERA", "MEE656"),
    ("CANO DELVALLE", "ARNALDO RAMON", "EAA311"),
    ("FERREYRA", "MARCOS JAVIER", "FUI264"),
]


class Command(BaseCommand):
    help = "Cruza la planilla de asegurados AMCA contra las polizas de Thames (por patente), distinguiendo compania."

    def _resumen_cuotas(self, poliza):
        cuotas = poliza.cuotas.all().order_by("cuota_nro")
        total = cuotas.count()
        pagadas = cuotas.filter(pagado=True).count()
        pendientes = total - pagadas
        debe = cuotas.filter(pagado=False).aggregate(s=Sum("monto"))["s"] or 0
        proxima = cuotas.filter(pagado=False).order_by("fecha_vencimiento").first()
        if proxima:
            fecha_txt = proxima.fecha_vencimiento.strftime("%d/%m/%Y")
            proxima_txt = f"prox. vto {fecha_txt} (cuota {proxima.cuota_nro})"
        else:
            proxima_txt = "sin pendientes"
        return total, pagadas, pendientes, debe, proxima_txt

    def handle(self, *args, **options):
        con_amca = []
        con_otra_cia = []
        no_existe = []
        vistas = set()

        for nombre, apellido, patente in CLIENTES_AMCA:
            patente = (patente or "").strip().upper()
            if not patente or patente in vistas:
                continue
            vistas.add(patente)

            polizas_patente = Poliza.objects.filter(patente__iexact=patente)

            poliza_amca = (
                polizas_patente.filter(compania__icontains="amca")
                .order_by("-id")
                .first()
            )

            if poliza_amca:
                total, pagadas, pendientes, debe, proxima_txt = self._resumen_cuotas(poliza_amca)
                con_amca.append(
                    (patente, apellido, nombre, poliza_amca.id, poliza_amca.estado,
                     total, pagadas, pendientes, debe, proxima_txt)
                )
                continue

            otras = polizas_patente.exclude(compania__icontains="amca")
            if otras.exists():
                companias = sorted(set(otras.values_list("compania", flat=True)))
                con_otra_cia.append((patente, apellido, nombre, companias))
            else:
                no_existe.append((patente, apellido, nombre))

        self.stdout.write(self.style.SUCCESS(f"\n✅ CON POLIZA DE AMCA CARGADA: {len(con_amca)}"))
        for patente, apellido, nombre, pid, estado, total, pagadas, pendientes, debe, proxima_txt in con_amca:
            self.stdout.write(
                f"  {patente} · {apellido}, {nombre} -> Poliza #{pid} (estado={estado}) | "
                f"Cuotas: {total} total, {pagadas} pagas, {pendientes} pendientes, debe ${debe} | {proxima_txt}"
            )

        self.stdout.write(self.style.WARNING(
            f"\n⚠️ EXISTE LA PATENTE PERO CON OTRA COMPANIA (falta cargar la de AMCA): {len(con_otra_cia)}"
        ))
        for patente, apellido, nombre, companias in con_otra_cia:
            lista_cias = ", ".join(companias)
            self.stdout.write(f"  {patente} · {apellido}, {nombre} -> tiene: {lista_cias}")

        self.stdout.write(self.style.ERROR(f"\n❌ NO EXISTE EN THAMES: {len(no_existe)}"))
        for patente, apellido, nombre in no_existe:
            self.stdout.write(f"  {patente} · {apellido}, {nombre}")

        total_v = len(vistas)
        self.stdout.write(
            f"\nTotal patentes cruzadas: {total_v} "
            f"({len(con_amca)} con AMCA, {len(con_otra_cia)} con otra cia, {len(no_existe)} no existen)"
        )