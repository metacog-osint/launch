"""Names as Launch reads them: vehicles, launch sites, payload programmes and their mission types, orbits.

Everything here is Launch's own reading of names, kept in tables so it can be checked and extended:

  vehicle()      one name per vehicle across the charted notices ("LM-7A"), GCAT ("Chang Zheng 7A") and Launch Library 2
                 ("Long March 7A"). Chinese Chang Zheng vehicles are written LM-, as the charted notices write them.
  site_name()    GCAT site codes and names to one name per launch site ("Vostochniy" -> "Vostochny"; the three
                 Vandenberg codes -> "Vandenberg").
  programmes()   payload programmes from payload, flight and mission names ("Yaogan-40 04A-C" -> Yaogan), each
                 with a mission type. Mission types of series the operator describes otherwise but public analysis
                 assesses as military (Yaogan, TJS) say "assessed". A payload GCAT files under a PLA body
                 (PLA_OWNERS) makes the launch "Military / intelligence" whatever its name.
  orbit_class()  GCAT's launch category ("Sat SSO D" -> SSO) or Launch Library 2's orbit ("PO" -> SSO / polar).
"""
from __future__ import annotations

import re

NOT_KNOWN = "Not known"

# ---------- vehicles ----------

_V = [  # (pattern on the upper-cased name, canonical name); the first match wins
    (r"^(?:LM|CZ|CHANG ?ZHENG|LONG ?MARCH)[\s-]*(\d+[A-Z]?)(?:\s*/\s*G)?", lambda m: "LM-" + m.group(1)),
    (r"^SOYUZ[\s-]*2[.\-]?1\s*([ABV])", lambda m: "Soyuz-2.1" + m.group(1).lower()),
    (r"^SOYUZ[\s-]*5", "Soyuz-5"),
    (r"^ANGARA[\s-]*1[.\-]?2", "Angara-1.2"),
    (r"^ANGARA[\s-]*A5", "Angara-A5"),
    (r"^PROTON", "Proton-M"),
    (r"^(?:KZ|KUAIZHOU)[\s-]*1A", "Kuaizhou-1A"),
    (r"^(?:KZ|KUAIZHOU)[\s-]*11", "Kuaizhou-11"),
    (r"^(?:CERES|GUSHENXING)[\s-]*1\s*S", "Ceres-1S"),
    (r"^(?:CERES|GUSHENXING)[\s-]*1", "Ceres-1"),
    (r"^(?:CERES|GUSHENXING)[\s-]*2", "Ceres-2"),
    (r"^(?:JIELONG|SMART DRAGON|SD)[\s-]*3", "Jielong-3"),
    (r"^(?:LIJIAN|KINETICA)[\s-]*1", "Lijian-1"),
    (r"^(?:LIJIAN|KINETICA)[\s-]*2", "Lijian-2"),
    (r"^(?:HYPERBOLA|SQX|SHUANG ?QUXIAN)[\s-]*1", "Hyperbola-1"),
    (r"^(?:ZHUQUE|ZQ)[\s-]*2E", "Zhuque-2E"),
    (r"^(?:ZHUQUE|ZQ)[\s-]*2", "Zhuque-2"),
    (r"^(?:ZHUQUE|ZQ)[\s-]*3", "Zhuque-3"),
    (r"^(?:GRAVITY|YINLI)[\s-]*1", "Gravity-1"),
    (r"^(?:GRAVITY|YINLI)[\s-]*2", "Gravity-2"),
    (r"^(?:TIANLONG|TL)[\s-]*2", "Tianlong-2"),
    (r"^(?:TIANLONG|TL)[\s-]*3", "Tianlong-3"),
    (r"^(?:NEBULA|XINGYUN)[\s-]*1", "Nebula-1"),
    (r"^FALCON ?9|^F9\b", "Falcon 9"),
    (r"^FALCON HEAVY", "Falcon Heavy"),
    (r"^(?:STARSHIP|SUPER HEAVY)", "Starship"),
    (r"^ELECTRON", "Electron"),
    (r"^ATLAS ?V", "Atlas V"),
    (r"^VULCAN", "Vulcan"),
    (r"^NEW GLENN", "New Glenn"),
    (r"^(?:FIREFLY )?ALPHA", "Alpha"),
    (r"^MINOTAUR", "Minotaur"),
    (r"^DELTA ?(?:IV|4)", "Delta IV Heavy"),
    (r"^H-?3", "H3"),
    (r"^H-?II?A|^H-?2A", "H-IIA"),
    (r"^ARIANE ?6", "Ariane 6"),
    (r"^ARIANE ?5", "Ariane 5"),
    (r"^VEGA ?C", "Vega C"),
    (r"^VEGA", "Vega"),
    (r"^PSLV", "PSLV"),
    (r"^GSLV ?MK ?III|^LVM ?3", "LVM3"),
    (r"^GSLV", "GSLV"),
    (r"^SSLV", "SSLV"),
    (r"^NURI|^KSLV", "Nuri"),
    (r"^CH[EO]+N?LL?IMA", "Chollima-1"),
    (r"^SIMORGH", "Simorgh"),
    (r"^QAEM", "Qaem-100"),
    (r"^QASED", "Qased"),
    (r"^ZOLJANAH", "Zoljanah"),
    (r"^SHAVIT", "Shavit"),
    (r"^KAIROS", "Kairos"),
    (r"^ERIS", "Eris"),
    (r"^SPECTRUM", "Spectrum"),
    (r"^YARS", "Yars (missile)"),
    (r"^BULAVA", "Bulava (missile)"),
    (r"^SARMAT", "Sarmat (missile)"),
]
_V = [(re.compile(p), v) for p, v in _V]
_V_UNKNOWN = re.compile(r"^(?:\?+|UNK(?:NOWN)?(?: LV)?|Z|UTC|-|)$")


def vehicle(raw: str | None) -> str:
    """One name per vehicle. Unread names come back as written (trimmed); none at all is NOT_KNOWN."""
    t = re.sub(r"\s+", " ", (raw or "").replace("�", " ")).strip()
    u = t.upper()
    if _V_UNKNOWN.match(u) or " OR " in u:
        return NOT_KNOWN if not (" OR " in u) else t
    for rx, out in _V:
        m = rx.search(u)
        if m:
            return out(m) if callable(out) else out
    return t


# ---------- launch sites ----------

# GCAT ShortName -> the name Launch shows. Codes sharing a name are one site (VSFB, VSFBS and VS are Vandenberg).
SITE_NAMES = {
    "Canaveral": "Cape Canaveral", "Kennedy": "Kennedy (KSC)", "Baykonur": "Baikonur", "Vostochniy": "Vostochny",
    "Hainan CLS": "Hainan commercial (Wenchang)", "Huang Hai": "Yellow Sea (sea launch)", "Tonghae": "Sohae",
    "Wallops MARS": "Wallops", "Wallops I": "Wallops", "ESRANGE": "Esrange", "Arabian Seaf": "Arabian Sea",
    "Eastern Med.": "Eastern Mediterranean", "Andoya": "Andøya", "Alcantara": "Alcântara", "Kapustin Yar": "Kapustin Yar",
    "East China Sea": "East China Sea (sea launch)", "Yangjiang": "Yangjiang (sea launch)",
    "Jeju": "Jeju (sea launch)", "Sriharikota": "Sriharikota",
    # GCAT's GIK-2 (Svobodniy, launches to 2006) is the old Svobodny cosmodrome, not Vostochny (VOST, "Vostochniy").
    "Svobodniy": "Svobodny", "Kirimati": "Kiritimati (sea launch)",
}
# Where a site has no closure history to choose between the two azimuths of an inclination: the way its
# launches go (geography and range safety: Vandenberg only south, Plesetsk only north), and, for sites that fly
# both ways, the way polar and sun-synchronous launches go.
SITE_DIRECTION = {
    "Vandenberg": "S", "Taiyuan": "S", "Jiuquan": "S", "Xichang": "S", "Sriharikota": "S", "Tanegashima": "S",
    "Kodiak": "S", "Wallops": "S", "Kii": "S", "Naro": "S", "Sohae": "S", "Semnan": "S", "Shahroud": "S",
    "Wenchang": "S", "Hainan commercial (Wenchang)": "S", "Yellow Sea (sea launch)": "S", "Plesetsk": "N",
    "Vostochny": "N", "Baikonur": "N", "Andøya": "N",
}
POLAR_DIRECTION = {"Cape Canaveral": "S", "Kennedy (KSC)": "S", "Mahia": "S", "Kourou": "N"}
# A south-going polar launch from the Cape does not fly its orbit's azimuth from the pad, which would cross the
# Florida peninsula: it heads south-east over the Atlantic, turns south and runs parallel to the east coast, close
# off Miami, then over Cuba (Spaceflight Now on OneWeb 16, 10 Jan 2023: "Southeast, then south from Cape
# Canaveral"; on SAOCOM 1B, 30 Aug 2020, the first such launch). An estimated path from these sites goes to this
# turn point ([lon, lat], about 20 NM off Boca Raton, approximate: the dog-leg's real place is not published) and
# takes the inclination's azimuth from there.
POLAR_CORRIDOR = {"Cape Canaveral": [-79.7, 26.3], "Kennedy (KSC)": [-79.7, 26.3]}
CORRIDOR_NOTE = "dog-leg: offshore along Florida's east coast to a turn point off Boca Raton (approximate), as the Cape's polar corridor flies"
# Other names for a site in Launch Library 2's pad and location text (lower case).
SITE_ALIASES = {"Hainan commercial (Wenchang)": ["commercial lc", "hainan commercial"], "Kourou": ["guiana"],
                "Andøya": ["andoya", "and�ya"], "Vandenberg": ["vandenberg"], "Kennedy (KSC)": ["kennedy"]}
# Neighbouring sites that fly the same programmes (for an inclination borrowed from the last launch).
SITE_SIBLINGS = {"Cape Canaveral": "Kennedy (KSC)", "Kennedy (KSC)": "Cape Canaveral",
                 "Wenchang": "Hainan commercial (Wenchang)", "Hainan commercial (Wenchang)": "Wenchang"}


def site_name(gcat_short: str | None) -> str | None:
    if not gcat_short:
        return None
    return SITE_NAMES.get(gcat_short, gcat_short)


# ---------- payload programmes and mission types ----------

MTYPES = ["LEO broadband constellation", "Communications", "Earth observation", "Military / intelligence",
          "Navigation", "Weather", "Science / exploration", "Technology / experimental", "Human spaceflight",
          "Station cargo", "Rideshare", "Test flight", "Missile / suborbital test", "Weapon (combat use)",
          "Reentry / landing", "Payload not known", "Not classified"]
COM, LEOBB, EO, MIL, NAV, WX, SCI, TECH, CREW, CARGO, RIDE, TEST, MSL, COMBAT, REENTRY = MTYPES[1], MTYPES[0], *MTYPES[2:15]
NO_PAYLOAD = MTYPES[15]  # no payload name to read (the map's "Unk Payload", a blank); "Not classified" = a name, no rule
MIL_A = MIL  # assessed: the operator describes the series otherwise (marked in PROGRAMMES' notes)
_NO_PAYLOAD = re.compile(r"\bUNK(?:NOWN)?\b|^[\s?\d:-]*$|^PAYLOADS?$")


def payload_unknown(payload: str | None) -> bool:
    """True when the payload field names nothing ("Unk Payload", "Payload", "???", blank)."""
    return bool(_NO_PAYLOAD.search((payload or "").strip().upper()))

# (pattern on the upper-cased text, programme, mission type, note). Ordered: the first programme found gives the
# mission type; every programme found is listed. Patterns need word starts so "SY" does not match inside words.
PROGRAMMES = [
    (r"RE-?ENTRY|\bLANDING\b|\bSPLASHDOWN|\bDEORBIT|\bRETURN\b", "Reentry or landing", REENTRY, ""),
    # China
    # "Yaogan" is the Chinese word for remote sensing: after a word of three or more letters it names a customer's
    # satellite ("Aerjiliya Yaogan-3A" is Algeria's Alsat-3A, "Bajistan Yaogan" Pakistan's), not the series.
    # "UTC " and "AND " are the charted labels' own words. YG with a one-digit number ("Tianyuan YG01") is not it.
    (r"(?:(?<=UTC |AND )|(?<![A-Z]{3} ))\bYAO ?GAN|\bYG-?[1-9]\d", "Yaogan", MIL_A,
     "assessed military; described as remote sensing"),
    (r"\bTJS\b|\bTJS-?\d|TONGXIN JISHU SHIYAN", "TJS", MIL_A, "assessed military; described as communications tests"),
    # Reviewed 15 Nov 2026 (names from records that were "Not classified"); facts not all verified.
    (r"\bWHG-?\d|HULIANWANG GAOGUI", "Satellite internet (GEO)", COM, "high-orbit satellite internet"),
    (r"\bZHTW\b|ZHIHUI TIANWANG", "Zhihui Tianwang", COM, ""),
    (r"GUOWANG|XINGWANG|SATNET|HULIANWANG|\bWHDW|\bWHJSW|\bDIGUI\b", "Guowang (SatNet)", LEOBB, ""),
    (r"QIANFAN|\bG60\b|SPACESAIL|THOUSAND SAILS", "Qianfan", LEOBB, ""),
    (r"HONGHU", "Honghu-3", LEOBB, ""),
    (r"\bCSSHQ|\bCHONG?FU SHIYONG|\bSPACEPLANE|\bEXPERIMENTAL SPACESHIP", "Reusable spacecraft (CSSHQ)", TECH, ""),
    # "Shiyan" is also the word for experimental ("Guanlan Shiyan Xing"): the series has its number after it.
    (r"(?<!JISHU )\bSHI ?YAN[ -]?\d|\bSY-?\d", "Shiyan", TECH, "some assessed military"),
    (r"\bSHI ?JIAN|\bSJ-?\d", "Shijian", TECH, "some assessed military"),
    (r"\bBEI ?DOU|\bBDS\b", "BeiDou", NAV, ""),
    (r"\bCENTISPACE|\bWEILI KONGJIAN", "CentiSpace", NAV, "navigation augmentation"),
    (r"\bFENG ?YUN|\bFY-?\d", "Fengyun", WX, ""),
    (r"\bTIANMU", "Tianmu-1", WX, "radio occultation"),
    (r"\bYUNHAI", "Yunhai", WX, "assessed military weather"),
    (r"\bYUNYAO", "Yunyao", WX, ""),
    (r"\bGAO ?FEN|\bGF-?\d", "Gaofen", EO, ""),
    (r"\bXINGSHIDAI|\bXSD\b|\bXSD-", "Xingshidai", EO, ""),
    (r"\bJILIN|\bJL-?1\b", "Jilin-1", EO, ""),
    (r"\bHAIYANG[ -]?\d|\bHY-?\d[A-Z]?\b", "Haiyang", EO, ""),
    (r"\bHUANJING|\bHJ-?\d", "Huanjing", EO, ""),
    (r"\bZIYUAN|\bZY-?\d", "Ziyuan", EO, ""),
    (r"\bLUDI TANCE|\bLT-?\d", "Ludi Tance", EO, ""),
    (r"\bTIANHUI", "Tianhui", EO, "mapping; some assessed military"),
    (r"\bSUPERVIEW|\bSIWEI", "SuperView", EO, ""),
    (r"\bPIESAT|\bTAIJING|\bXIGUANG|\bTIANYAN|\bKAIYUN|\bGEESPACE|\bGEELY", "Chinese commercial", EO, ""),
    (r"\bTIANQI", "Tianqi", COM, ""),
    (r"\bJIAOTONG|\bJIANTONG|\bVDES\b", "Jiaotong VDES", COM, ""),
    (r"\bTIANYI|\bTIANPING|\bLONGJIANG|\bDIER\b|\bDEAR-\d|\bXIWANG|\bXI WANG", "Chinese technology", TECH, ""),
    (r"\bZHANG ?HENG", "Zhangheng", SCI, ""),
    (r"\bQINGZHOU", "Qingzhou", CARGO, ""),
    (r"\bTIANLIAN", "Tianlian", COM, "data relay"),
    (r"\bTIANTONG", "Tiantong", COM, ""),
    (r"\bZHONGXING|\bCHINASAT|\bZX-?\d", "Zhongxing (ChinaSat)", COM, ""),
    (r"\bSHEN ?ZHOU|\bSZ-?\d", "Shenzhou", CREW, ""),
    (r"\bMENGZHOU", "Mengzhou", CREW, ""),
    (r"\bTIAN ?ZHOU|\bTZ-?\d", "Tianzhou", CARGO, ""),
    (r"\bCHANG['\s-]?E\b|\bCHANGE-?\d|\bQUEQIAO|\bDRO-[AB]", "Chang'e and lunar", SCI, ""),
    (r"\bTIANWEN", "Tianwen", SCI, ""),
    (r"\bEINSTEIN PROBE|\bSVOM\b|\bXUNTIAN|\bASO-S|\bSMILE\b", "Chinese science", SCI, ""),
    # Russia
    (r"\bRASSVET|BUREAU ?1440|\bBYURO", "Rassvet", LEOBB, ""),
    (r"\bGLONASS", "GLONASS", NAV, ""),
    (r"\bPROGRESS|7K-TGM", "Progress", CARGO, ""),
    (r"\bSOYUZ MS|11F732", "Soyuz MS", CREW, ""),
    (r"\bMETEOR\b|\bMETEOR-M", "Meteor-M", WX, ""),
    (r"\bELEKTRO", "Elektro-L", WX, ""),
    (r"\bARKTIKA", "Arktika-M", WX, ""),
    (r"\bKONDOR-FKA|\bRESURS|\bKANOPUS|\bAIST\b|\bOBZOR", "Russian Earth observation", EO, ""),
    (r"\bLUCH|\bEKSPRESS|\bEXPRESS-A|\bYAMAL|\bGONETS|\bSFERA|\bSKIF|\bMARATHON", "Russian communications", COM, ""),
    (r"\bKOSMOS|\bCOSMOS[ -]?\d|\b14F\d|\bRODNIK|\bNIVELIR|\bMERIDIAN|\bLOTOS|\bPION\b|\bBARS\b|\bKONDOR|\bRAZDAN|"
     r"\bTUNDRA|\bEKS\b|\bKUPOL|\bLIPS\b|\bMOZHAETS|\bNORD", "Kosmos (Russian military)", MIL, ""),
    (r"\bBION\b|\bLUNA[ -]?\d|\bIONOSFERA", "Russian science", SCI, ""),
    # United States and commercial
    (r"\bSTARLINK", "Starlink", LEOBB, ""),
    (r"\bKUIPER|\bAMAZON LEO|\bL[EV]-\d\d", "Amazon Leo (Kuiper)", LEOBB, ""),
    (r"\bONEWEB", "OneWeb", LEOBB, ""),
    (r"\bSTARSHIELD|\bSBST\b|\bNROL|\bNRO\b|\bUSA \d", "NRO / US national security", MIL, ""),
    (r"\bUSSF|\bSDA\b|\bTRANCHE|\bT[12]T[LR]|\bGSSAP|\bSBIRS|\bOPIR|\bWGS\b|\bAEHF|\bMUOS|\bX-37|\bOTV-|"
     r"\bNTS-3|\bSILENTBARKER|\bDMSP|\bWSF-M", "US Space Force", MIL, ""),
    (r"\bGPS\b|\bGPS ?I|\bNAVSTAR", "GPS", NAV, ""),
    (r"\bGALILEO", "Galileo", NAV, ""),
    (r"\bIRNSS|\bNAVIC|\bNVS-", "NavIC", NAV, ""),
    (r"\bQZS|\bMICHIBIKI", "QZSS", NAV, ""),
    (r"\bTRANSPORTER|\bBANDWAGON|\bRIDESHARE", "Rideshare", RIDE, ""),
    (r"\bSTART ME UP\b|\bTATARA-1", "Rideshare", RIDE, ""),
    (r"\bDRAGON C20[67]|\bDRAGON C21[02]|\bCREW-\d|\bCREW DRAGON|\bAX-\d|\bAXIOM|\bPOLARIS|\bFRAM2|\bSTARLINER|\bCFT\b|\bVAST\b", "Crewed (US)", CREW, ""),
    (r"\bDRAGON C20[89]|\bDRAGON C211|\bCRS-|\bCARGO DRAGON|\bCYGNUS|\bNG-\d|\bDREAM ?CHASER|\bHTV", "Station cargo (US, Japan)", CARGO, ""),
    (r"\bSTARSHIP|\bSHIP \d|\bIFT-?\d|\bFLIGHT TEST", "Starship flight test", TEST, ""),
    (r"\bIGS\b|\bIGS-|\bOFE[KQ]|\bMAL+IGYONG|\bMANLIGYEONG|\bVICTUS|\bSTP-S|\bKIRAMEKI|\bDSN \d|\bSURAYA|\bNOOR\b|\b425 ?PROJECT|\bPROJECT 425|\bANASIS|\bSPAINSAT|\bSKYNET|"
     r"\bSYRACUSE|\bSICRAL|\bCSO-|\bSARAH\b|\bRISAT", "Other military", MIL, ""),
    (r"\bTROPICS\b|\bGOES|\bJPSS|\bNOAA-?\d|\bMETOP|\bMTG-|\bGEO-KOMPSAT-2|\bINSAT-3D|\bINSAT-2DS", "Weather (other)", WX,
     ""),
    (r"\bCELESTE\b", "Celeste (ESA LEO-PNT)", NAV, "navigation demonstration"),
    (r"\bDS-SAR\b|\bQINLING|\bPUJIANG|\bPRCS-EO", "Earth observation (other)", EO, ""),
    (r"\bSENTINEL|\bLANDSAT|\bEARTHCARE|\bSWOT|\bNISAR|\bPACE\b|\bBIOMASS|\bCO3D|\bPLEIADES|\bWORLDVIEW|"
     r"\bLEGION|\bPELICAN|\bSKYSAT|\bFLOCK|\bSUPERDOVE|\bBLACKSKY|\bICEYE|\bCAPELLA|\bUMBRA|\bQPS-SAR|\biQPS|"
     r"\bSYNSPECTIVE|\bSTRIX|\bSATELLOGIC|\bNUSAT|\bEOS-\d|\bCARTOSAT|\bOCEANSAT|\bKOMPSAT|\bCAS500|\bALOS|"
     r"\bKHAYYAM|\bPRSC|\bPRSS|\bMOUNTAIN GOD|\bSEA GOD|\bHAWK \d|\bHAWKEYE|\bCOSMO-SKYMED|\bTHEOS|\bFORMOSAT|"
     r"\bGOSAT|\bALSAT|\bTELEOS|\bNEONSAT|\bMISRSAT|\bBEIJING-3|\bGUANGCHUAN|\bDONGFANG|\bHAISHAO|\bCHUTIAN|"
     r"\bWUHAN-1|\bJILI\b|\bCHAMRAN|\bPARS\b|\bKOWSAR|\bHODHOD|\bSEO\b|\bLEMUR", "Earth observation (other)", EO, ""),
    (r"\bSES\b|\bO3B|\bINTELSAT|\bEUTELSAT|\bVIASAT|\bINMARSAT|\bECHOSTAR|\bSIRIUS|\bSXM|\bASTRA \d|\bTHAICOM|"
     r"\bNUSANTARA|\bTURKSAT|\bARABSAT|\bJCSAT|\bSUPERBIRD|\bOPTUS|\bKOREASAT|\bAMAZONAS|\bHISPASAT|\bTELKOMSAT|"
     r"\bGSAT|\bCMS-0|\bTHURAYA|\bASTRANIS|\bGLOBALSTAR|\bIRIDIUM|\bBLUEBIRD|\bLYNK|\bTDRS|\bNILESAT|\bMEASAT|"
     r"\bAPSTAR|\bASIASAT|\bBADR|\bYAHSAT|\bAL YAH|\bKINEIS|\bOTC\b|\bSWARM|\bSPACEBEE|\bDROR|\bE-SPACE|\bNBN|"
     r"\bGALAXY \d|\bOVZON|\bMERAH PUTIH|\bSPACEMOBILE|\bLYRA\b|\bPAKSAT|\bNAHID|\bASBM",
     "Communications (other)", COM, ""),
    (r"\bPSYCHE|\bEUROPA|\bIM-\d|\bINTUITIVE MACHINES|\bODYSSEUS|\bATHENA\b|\bBLUE GHOST|\bPEREGRINE|\bHAKUTO|"
     r"\bRESILIENCE|\bSLIM\b|\bXRISM|\bCHANDRAYAAN|\bADITYA|\bPUNCH\b|\bSPHEREX|\bJUICE|\bHERA\b|\bESCAPADE|"
     r"\bIMAP\b|\bARTEMIS|\bTRACERS|\bEUCLID|\bPROBA|\bMMX\b|\bNGRST|\bROMAN\b|\bLUNAR|\bXPOSAT|\bPREFIRE|"
     r"\bAOMEN KEXUE", "Science (other)", SCI, ""),
    (r"\bSPADEX|\bADRAS|\bLM-400|\bDISKSAT|\bVCLS|\bRAISE-\d|\bVEP-\d|\bS-STEP|\bBLUE RING|\bSTARFALL|\bVARDA|"
     r"\bMEHDA|\bKAIHAN|\bNEXTSAT|\bNEXSAT|\bTECH DEMO|\bTANTRUM\b|\bSAHMAN|\bSWIFT REBOOST|\bMRV\b|\bMEPS?\b|"
     r"\bISTD-\d|\bJIGUANG ZUANSHI", "Technology (other)", TECH, ""),
    (r"\bMACH-TB|\bHASTE\b", "Hypersonic test (HASTE)", MSL, "suborbital"),
    (r"\bASAT\b|\bNUDOL", "ASAT test (possible)", MSL, ""),
    (r"\bYARS|\bBULAVA|\bSARMAT|\bSINEVA|\bICBM|\bSLBM|\bMISSILE|\bAVANGARD|\bMINUTEMAN|\bTRIDENT|\bJULANG|"
     r"\bJL-[23]\b|\bDF-\d|\bFOBS\b", "Missile test", MSL, ""),
    (r"\bMAIDEN|\bINAUGURAL|\bTEST FLIGHT|\bDEMO FLIGHT|\bFIRST FLIGHT|\bDUMMY|\bMASS SIMULATOR|"
     r"\bTEST (?:PAYLOAD|LAUNCH|MICROSAT)|\bCERT-\d|\bTEST\b|\bGMM\b|\bGLHF\b|\bJINTA\b|\bVARISAT|"
     r"\bTANKI UCHAIGEGATA|\bSOLARAS|\bGOING FULL SPECTRUM|\bONWARD AND UPWARD|\b6 X SATS\b(?=.*CERES-2)",
     "Test flight", TEST, "maiden flights, mass models"),
    (r"\bMULTIPLE PAYLOADS", "Rideshare", RIDE, ""),
    # Reviewed 16 Nov 2026: the eight names left "Not classified". Last in the table, so
    # they give the mission type only where no other row matched.
    (r"\bHORUS\b|\bHELUSI", "Earth observation (other)", EO, ""),
    (r"\bSIXIANG|\bSKYSIGHT|\bKUANGDA NANHU|\bHONGKOU FUXING|\bZHONGDIAN NONGCHUANG|\bENSHI\b|\bKUNPENG",
     "Chinese commercial", EO, ""),
    (r"\bZHONGKE\b|\bZHONGKE-1\b|\bAIRSAT|\bBEIBUWAN|\bMUDUO|\bJINGAN MENGXIANG|\bZK-1[45]\b", "Zhongke-1 (AIRSAT)",
     EO, ""),
    (r"\bTIANXING|\bCHUANGXIN-?\d", "Chinese technology", TECH, ""),
    (r"(?<!YUNXIAO )\bTANLUO?ZHE", "Chinese science", SCI, ""),  # Tanluzhe-1, not the Yunxiao Tanluzhe of 2026-220
    (r"COSMOS WILL SEE YOU NOW", "Open Cosmos telecom", LEOBB, "Ka-band LEO telecom constellation"),
    (r"\bLINGXI|\bYINHE-\d", "GalaxySpace", TECH, "communications tests"),
]
# GCAT's organisation codes for PLA bodies (gcat-orgs: ZZB General Armaments Dept, ZLZB Strategic Support Force,
# JHB Military Aerospace Force; GCAT keeps filing payloads under ZZB and ZLZB after the 2016 and 2024 reorganisations).
PLA_OWNERS = {"PLA", "ZZB", "ZLZB", "JHB", "PLAAF", "PLANS", "PLARF", "PLA2AC"}
PLA_OWNED = "PLA owner (GCAT)"
PROGRAMMES = [(re.compile(p), name, mt, note) for p, name, mt, note in PROGRAMMES]
NOTES = {name: note for _, name, _, note in PROGRAMMES if note}
NOTES[PLA_OWNED] = "a payload GCAT files under a PLA body"
MTYPE_OF = {name: mt for _, name, mt, _ in PROGRAMMES}
MTYPE_OF[PLA_OWNED] = MIL

LL2_MTYPE = {"Communications": COM, "Earth Science": EO, "Government/Top Secret": MIL, "Navigation": NAV,
             "Resupply": CARGO, "Human Exploration": CREW, "Tourism": CREW, "Planetary Science": SCI,
             "Astrophysics": SCI, "Heliophysics": SCI, "Robotic Exploration": SCI, "Lunar Exploration": SCI,
             "Technology": TECH, "Test Flight": TEST, "Dedicated Rideshare": RIDE, "Meteorology": WX}


def pla_owned(owners) -> bool:
    """True when GCAT files a payload under a PLA body ("ZLZB", "ZZB/CAST", "ZLZB?")."""
    return any(c.strip().rstrip("?") in PLA_OWNERS for o in owners or () for c in o.split("/"))


def programmes(*texts: str | None, owners=None) -> tuple[list[str], str]:
    """Programmes found in the texts and the mission type of the first, or ([], 'Not classified'). A payload owner
    GCAT names as a PLA body adds PLA_OWNED and makes the type military (a reentry or landing stays one)."""
    # The map's labels join words with "_"; texts are kept apart so no pattern reads across two of them.
    u = " | ".join(t for t in texts if t).upper().replace("_", " ")
    found, mtype = [], None
    for rx, name, mt, _ in PROGRAMMES:
        if rx.search(u) and name not in found:
            found.append(name)
            mtype = mtype or mt
    if pla_owned(owners):
        found.append(PLA_OWNED)
        if mtype != REENTRY:
            mtype = MIL
    return found, mtype or MTYPES[-1]


# ---------- orbits ----------

ORBITS = ["LEO", "SSO / polar", "Space station", "MEO", "GTO / GEO", "HEO / Molniya", "Deep space / lunar",
          "Suborbital", NOT_KNOWN]
GCAT_ORBIT = {"LEO": "LEO", "SSO": "SSO / polar", "ISS": "Space station", "LSS": "Space station", "MEO": "MEO",
              "MTO": "MEO", "GTO": "GTO / GEO", "GEO": "GTO / GEO", "STO": "GTO / GEO", "MOL": "HEO / Molniya",
              "HEO": "HEO / Molniya", "EEO": "Deep space / lunar", "DSO": "Deep space / lunar"}
LL2_ORBIT = {"LEO": "LEO", "VLEO": "LEO", "SSO": "SSO / polar", "PO": "SSO / polar", "MEO": "MEO", "GTO": "GTO / GEO",
             "GEO": "GTO / GEO", "GSO": "GTO / GEO", "SSTO": "GTO / GEO", "HEO": "HEO / Molniya", "Molniya": "HEO / Molniya",
             "Elliptical": "HEO / Molniya", "TLI": "Deep space / lunar", "Lunar": "Deep space / lunar",
             "Heliocentric": "Deep space / lunar", "Heliocentric N/A": "Deep space / lunar", "L1": "Deep space / lunar",
             "L2": "Deep space / lunar", "Mars": "Deep space / lunar", "Sub": "Suborbital", "Suborbital": "Suborbital"}
# Inclination (degrees) typical of a class, for an azimuth when no payload inclination is known.
CLASS_INC = {"SSO / polar": 97.6}
STATION_INC = {"ISS": 51.64, "LSS": 41.47}


# ---------- launch kinds ----------
# GCAT's LaunchCode, first letter (planet4589.org/space/gcat/web/launch/lcols.html, read 15 Nov 2026): O orbital,
# D deep space, N near-orbital (added 2026), S suborbital rocket other than a missile, Y suborbital flight with people
# aboard, A atmospheric rocket, M military missile, L high-apogee lofted missile test (added 2026). GCAT's Category
# "Weapon" and "Interceptor Weapon" mark a missile fired in combat (an attack, or an interception of one).
GCAT_KIND = {"O": "orbital", "D": "deep space", "N": "near-orbital", "S": "suborbital", "Y": "crewed suborbital",
             "A": "atmospheric", "M": "missile", "L": "lofted missile"}
ORBITAL_KINDS = ("orbital", "deep space", "near-orbital")
COMBAT_CATEGORIES = {"Weapon", "Interceptor Weapon"}
KINDS = ["Orbital", "Suborbital rocket", "Crewed suborbital", "Atmospheric test", "Missile test",
         "Lofted missile test", "Combat launch", NOT_KNOWN]
ORBITAL, SUBORBITAL, CREWED_SUB, ATMOS, MISSILE, LOFTED, COMBAT_LAUNCH = KINDS[:7]
KIND_NOTES = {
    ORBITAL: "reaches orbit, or leaves Earth (GCAT codes O, D and N)",
    SUBORBITAL: "a suborbital rocket other than a missile: sounding rockets, uncrewed New Shepard, hypersonic test "
                "vehicles (GCAT code S)",
    CREWED_SUB: "a suborbital flight with people aboard: New Shepard, SpaceShipTwo (GCAT code Y)",
    ATMOS: "an atmospheric rocket: flights that stay low, such as hypersonic test aircraft and targets (GCAT code A)",
    MISSILE: "a military missile fired in a test, an exercise or as a target (GCAT code M)",
    LOFTED: "a missile test on a lofted, high-apogee path (GCAT code L)",
    COMBAT_LAUNCH: "a missile fired in combat: an attack, or an interception of one (GCAT code M, category Weapon "
                   "or Interceptor Weapon)",
    NOT_KNOWN: "a charted notice or notice set that no GCAT launch is joined to",
}
# Mission type for a suborbital launch whose payload names give none (GCAT categories of sounding-rocket flights).
_SUB_TECH = {"Test", "Tech", "Hypersonic", "Aeron", "Target", "Static Fail", "R&D"}


def launch_kind(gcat_kind: str | None, category: str | None = None) -> str:
    """Launch's kind for a GCAT launch (its ledger `kind`, from LaunchCode, and its Category)."""
    k = (gcat_kind or "orbital").strip()
    if k in ORBITAL_KINDS:
        return ORBITAL
    if k == "missile":
        return COMBAT_LAUNCH if (category or "").strip() in COMBAT_CATEGORIES else MISSILE
    return {"suborbital": SUBORBITAL, "crewed suborbital": CREWED_SUB, "atmospheric": ATMOS,
            "lofted missile": LOFTED}.get(k, NOT_KNOWN)


def kind_mtype(kind: str, mtype: str, category: str | None = None) -> str:
    """The mission type of a suborbital launch: a missile's or a crewed flight's is its kind's; a suborbital
    rocket's is what its payload names give, else science or technology by GCAT's category."""
    if kind == COMBAT_LAUNCH:
        return COMBAT
    if kind in (MISSILE, LOFTED):
        return MSL
    if kind == CREWED_SUB:
        return CREW
    if kind in (SUBORBITAL, ATMOS) and mtype in (MTYPES[-1], NO_PAYLOAD):
        return TECH if kind == ATMOS or (category or "").strip() in _SUB_TECH else SCI
    return mtype


def gcat_orbit_code(category: str | None) -> str | None:
    t = (category or "").split()
    return t[1] if len(t) > 1 and t[0] == "Sat" else None


def orbit_class(gcat_category: str | None = None, ll2_orbit: str | None = None) -> str:
    code = gcat_orbit_code(gcat_category)
    if code and code in GCAT_ORBIT:
        return GCAT_ORBIT[code]
    if ll2_orbit and ll2_orbit in LL2_ORBIT:
        return LL2_ORBIT[ll2_orbit]
    return NOT_KNOWN
