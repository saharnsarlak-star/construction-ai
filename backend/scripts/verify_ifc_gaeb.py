"""Generate minimal IFC + GAEB samples and run extractors. Print real output."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_minimal_ifc(path: Path) -> None:
    import ifcopenshell
    import ifcopenshell.api

    # Prefer high-level API when available; fall back to manual entities.
    try:
        model = ifcopenshell.file(schema="IFC4")
        project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="TenderRisk Test Project")
        ifcopenshell.api.run("unit.assign_unit", model)
        context = ifcopenshell.api.run("context.add_context", model, context_type="Model")
        body = ifcopenshell.api.run(
            "context.add_context",
            model,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=context,
        )
        site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Test Site")
        building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Test Building")
        storey = ifcopenshell.api.run(
            "root.create_entity", model, ifc_class="IfcBuildingStorey", name="Level 01"
        )
        ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[site])
        ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, products=[building])
        ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, products=[storey])
        wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name="Wall-A")
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[wall])
        # Fire-related property for highlight path
        pset = ifcopenshell.api.run("pset.add_pset", model, product=wall, name="Pset_WallCommon")
        ifcopenshell.api.run(
            "pset.edit_pset",
            model,
            pset=pset,
            properties={"FireRating": "REI 90", "IsExternal": True, "LoadBearing": True},
        )
        model.write(str(path))
        return
    except Exception as api_exc:  # noqa: BLE001
        print("ifcopenshell.api path failed, writing SPF manually:", api_exc)

    # Minimal hand-written IFC4 SPF with project/site/building/storey/wall
    spf = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('minimal.ifc','2026-01-01T00:00:00',('TenderRisk'),('TenderRisk'),'IfcOpenShell','IfcOpenShell','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPERSON($,$,'Tester',$,$,$,$,$);
#2=IFCORGANIZATION($,'TenderRisk',$,$,$);
#3=IFCPERSONANDORGANIZATION(#1,#2,$);
#4=IFCAPPLICATION(#2,'0.1','TenderRisk AI','TenderRisk');
#5=IFCOWNERHISTORY(#3,#4,$,.ADDED.,$,$,$,0);
#6=IFCDIRECTION((1.,0.,0.));
#7=IFCDIRECTION((0.,0.,1.));
#8=IFCCARTESIANPOINT((0.,0.,0.));
#9=IFCAXIS2PLACEMENT3D(#8,#7,#6);
#10=IFCDIRECTION((0.,1.,0.));
#11=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#9,#10);
#12=IFCDIMENSIONALEXPONENTS(0,0,0,0,0,0,0);
#13=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#14=IFCUNITASSIGNMENT((#13));
#15=IFCPROJECT('2O2a2ntuL8xORtNJkY7RL2',#5,'TenderRisk Test Project',$,$,$,$,(#11),#14);
#20=IFCSITE('2O2a2ntuL8xORtNJkY7RL3',#5,'Test Site',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);
#21=IFCBUILDING('2O2a2ntuL8xORtNJkY7RL4',#5,'Test Building',$,$,$,$,$,.ELEMENT.,$,$,$);
#22=IFCBUILDINGSTOREY('2O2a2ntuL8xORtNJkY7RL5',#5,'Level 01',$,$,$,$,$,.ELEMENT.,0.);
#30=IFCRELAGGREGATES('2O2a2ntuL8xORtNJkY7RL6',#5,$,$,#15,(#20));
#31=IFCRELAGGREGATES('2O2a2ntuL8xORtNJkY7RL7',#5,$,$,#20,(#21));
#32=IFCRELAGGREGATES('2O2a2ntuL8xORtNJkY7RL8',#5,$,$,#21,(#22));
#40=IFCWALL('2O2a2ntuL8xORtNJkY7RL9',#5,'Wall-A','Test wall',$,$,$,$,$);
#41=IFCRELCONTAINEDINSPATIALSTRUCTURE('2O2a2ntuL8xORtNJkYA000',#5,$,$,(#40),#22);
#50=IFCPROPERTYSINGLEVALUE('FireRating',$,IFCLABEL('REI 90'),$);
#51=IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.T.),$);
#52=IFCPROPERTYSET('2O2a2ntuL8xORtNJkYA001',#5,'Pset_WallCommon',$,(#50,#51));
#53=IFCRELDEFINESBYPROPERTIES('2O2a2ntuL8xORtNJkYA002',#5,$,$,(#40),#52);
ENDSEC;
END-ISO-10303-21;
"""
    path.write_text(spf, encoding="utf-8")


def build_minimal_gaeb_x83(path: Path) -> None:
    # Minimal GAEB DA XML 3.2 X83. OZ is Item/@RNoPart (not a child <OZ> element).
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">
  <GAEBInfo>
    <Version>3.2</Version>
    <VersDate>2013-10</VersDate>
    <Date>2026-01-01</Date>
    <Time>12:00:00</Time>
  </GAEBInfo>
  <Award>
    <DP>83</DP>
    <Project>
      <Name>TenderRisk Test LV</Name>
    </Project>
    <BoQ>
      <BoQInfo>
        <Name>Test BoQ</Name>
        <LblBoQ>LV Test</LblBoQ>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Rohbau</LblTx>
          <Itemlist>
            <Item RNoPart="0010">
              <Qty>100.000</Qty>
              <QU>m2</QU>
              <Description>
                <CompleteText>
                  <OutlineText>
                    <OutlTxt>
                      <TextOutlTxt>Mauerwerk Innenwand</TextOutlTxt>
                    </OutlTxt>
                  </OutlineText>
                </CompleteText>
              </Description>
            </Item>
            <Item RNoPart="0020">
              <Qty>25.500</Qty>
              <QU>m3</QU>
              <Description>
                <CompleteText>
                  <OutlineText>
                    <OutlTxt>
                      <TextOutlTxt>Stahlbeton C30/37</TextOutlTxt>
                    </OutlTxt>
                  </OutlineText>
                </CompleteText>
              </Description>
            </Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""
    path.write_text(xml, encoding="utf-8")


def main() -> int:
    from app.services.gaeb_extractor import extract_gaeb
    from app.services.ifc_extractor import extract_ifc

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ifc_path = tmp_path / "minimal.ifc"
        gaeb_path = tmp_path / "minimal.X83"

        print("=== Building samples ===")
        build_minimal_ifc(ifc_path)
        build_minimal_gaeb_x83(gaeb_path)
        print(f"IFC bytes: {ifc_path.stat().st_size}")
        print(f"GAEB bytes: {gaeb_path.stat().st_size}")

        print("\n=== IFC extract_ifc ===")
        ifc_res = extract_ifc(ifc_path)
        print("method:", ifc_res.extraction_method)
        print("confidence:", ifc_res.confidence_score)
        print("needsManualReview:", ifc_res.needs_manual_review)
        print("error:", ifc_res.error)
        print("notes:", ifc_res.notes)
        print("structured keys:", list((ifc_res.structured or {}).keys()))
        print(
            "elements_by_discipline:",
            json.dumps(ifc_res.structured.get("elements_by_discipline"), ensure_ascii=False, indent=2),
        )
        print(
            "spatial_hierarchy (first 8):",
            json.dumps((ifc_res.structured.get("spatial_hierarchy") or [])[:8], ensure_ascii=False, indent=2),
        )
        print(
            "property_highlights:",
            json.dumps(ifc_res.structured.get("property_highlights"), ensure_ascii=False, indent=2)[:2000],
        )
        print("--- merged_text ---")
        print(ifc_res.merged_text[:2500])

        print("\n=== GAEB extract_gaeb ===")
        gaeb_res = extract_gaeb(gaeb_path)
        print("method:", gaeb_res.extraction_method)
        print("confidence:", gaeb_res.confidence_score)
        print("needsManualReview:", gaeb_res.needs_manual_review)
        print("error:", gaeb_res.error)
        print("notes:", gaeb_res.notes)
        print(
            "structured summary:",
            json.dumps(
                {
                    "source_version": gaeb_res.structured.get("source_version"),
                    "exchange_phase": gaeb_res.structured.get("exchange_phase"),
                    "grand_total": gaeb_res.structured.get("grand_total"),
                    "item_count": gaeb_res.structured.get("item_count"),
                    "items": gaeb_res.structured.get("items"),
                    "validation_results": gaeb_res.structured.get("validation_results"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        print("--- merged_text ---")
        print(gaeb_res.merged_text[:2500])

        ok = (
            ifc_res.extraction_method == "ifc_native"
            and ifc_res.confidence_score >= 90
            and not ifc_res.error
            and gaeb_res.extraction_method == "gaeb_native"
            and gaeb_res.confidence_score >= 90
            and (gaeb_res.structured.get("item_count") or 0) >= 1
        )
        print("\n=== VERDICT ===", "PASS" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
