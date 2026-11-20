# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the offline PyAEDT API search and the ``find_api`` tool."""

import json
import textwrap

import pytest

from ansys.aedt.mcp import tools  # noqa: F401 - import to register tools
from ansys.aedt.mcp.api_search import PyAEDTApiIndex, get_api_index, tokenize

FAKE_MODULE = textwrap.dedent(
    '''
    class Modeler:
        """Geometry modeler."""

        def create_box(self, origin, sizes, name=None):
            """Create a box.

            References
            ----------
            >>> oEditor.CreateBox
            """
            return self.oeditor.CreateBox([], [])

        def create_cylinder(self, origin, radius):
            """Create a cylinder."""
            return self._oeditor.CreateCylinder([], [])

        @property
        def object_names(self):
            """List of object names."""
            return []

        def _private(self):
            return self.oeditor.Delete()

        def _export_report_inner(self, path):
            return self.omodule.ExportReport(path)


    class Hfss(Modeler):
        """HFSS application."""

        def assign_radiation_boundary_to_objects(self, assignment, name=None):
            """Assign a radiation boundary to one or more objects.

            References
            ----------
            >>> oModule.AssignRadiation
            """
            return self.omodule.AssignRadiation([])

        def assign_current(self, assignment, amplitude=1):
            """Assign current excitation."""

            return self._create_boundary("c", {}, "Current")

        def export_csv(self, path):
            """Export results to CSV."""

            return self._export_to_csv(path)

        def export_report(self, path):
            """Export a report through two helpers."""

            return self._export_report_outer(path)

        def assign_port(self, assignment):
            """Assign a port."""

            return self._create_boundary("o", {}, boundary_type="Wave Port")

        def assign_unknown(self, assignment):
            """Assign a type with no native mapping."""

            return self._create_boundary("u", {}, "Unknown Type")

        def refresh_names(self):
            """Only reads state through a helper."""

            return self._read_names()

        def _export_to_csv(self, path):
            return self.odesign.ExportToCsv(path)

        def _export_report_outer(self, path):
            self._export_report_inner(path)

        def _read_names(self):
            self.odesign.ChangeProperty([])
            return self.oeditor.GetObjectsInGroup("Solids")

        def __getitem__(self, key):
            return self.oeditor.Delete(key)

        def _create_boundary(self, name, props, boundary_type):
            return Boundary(self, name, props, boundary_type).create()


    class Icepak:
        """Icepak application with a same-named helper making a different call."""

        def export_csv(self, path):
            """Export Icepak results to CSV."""

            return self._export_to_csv(path)

        def _export_to_csv(self, path):
            return self.odesign.ExportFieldsSummary(path)


    class Boundary:
        """Turns a boundary type into the matching native AssignXxx call."""

        def create(self):
            if self.type == "Current":
                return self._app.oboundary.AssignCurrent([])
            elif self.type in ("Wave Port", "Floquet Port"):
                return self._app.oboundary.AssignWavePort([])
            return False


    def helper_function(value):
        """Do something unrelated."""
        return os.Path(value)
    '''
)


@pytest.fixture
def fake_index(tmp_path):
    (tmp_path / "fake.py").write_text(FAKE_MODULE, encoding="utf-8")
    (tmp_path / "extensions").mkdir()
    (tmp_path / "extensions" / "ui.py").write_text("def create_box_ui():\n    pass\n")
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    return PyAEDTApiIndex(package_root=tmp_path)


class TestTokenize:
    def test_splits_camel_and_snake_case(self):
        tokens = tokenize("oEditor.CreateBox create_box")
        assert {"editor", "create", "box", "createbox"} <= set(tokens)

    def test_folds_plurals(self):
        assert tokenize("boundaries ports") == ["boundary", "port"]


class TestPyAEDTApiIndex:
    def test_indexes_public_api_only(self, fake_index):
        fake_index.ensure_loaded()
        names = {e.name for e in fake_index.entries}
        assert {"Modeler", "Hfss", "create_box", "object_names", "helper_function"} <= names
        assert "_private" not in names
        assert "create_box_ui" not in names
        assert fake_index.parse_errors and "broken.py" in fake_index.parse_errors[0]

    def test_property_kind_and_signature(self, fake_index):
        fake_index.ensure_loaded()
        entry = next(e for e in fake_index.entries if e.name == "object_names")
        assert entry.kind == "property"
        create_box = next(e for e in fake_index.entries if e.name == "create_box")
        assert create_box.signature == "(origin, sizes, name=None)"
        assert create_box.qualname == "ansys.aedt.core.fake.Modeler.create_box"

    def test_native_calls_from_references_and_body(self, fake_index):
        fake_index.ensure_loaded()
        cyl = next(e for e in fake_index.entries if e.name == "create_cylinder")
        assert cyl.native_api == ["oeditor.CreateCylinder"]
        box = next(e for e in fake_index.entries if e.name == "create_box")
        assert box.native_api == ["oEditor.CreateBox"]
        helper = next(e for e in fake_index.entries if e.name == "helper_function")
        assert helper.native_api == []

    def test_native_query_maps_to_pyaedt(self, fake_index):
        hits = fake_index.search("oModule.AssignRadiation", scope="native")
        assert hits[0][0].name == "assign_radiation_boundary_to_objects"
        assert all(e.native_api for e, _ in hits)

    def test_pyaedt_name_query(self, fake_index):
        hits = fake_index.search("create_cylinder")
        assert hits[0][0].name == "create_cylinder"

    def test_filters(self, fake_index):
        hits = fake_index.search("create", kinds=["property"])
        assert hits == []
        hits = fake_index.search("radiation boundary", module="Hfss.")
        assert [e.name for e, _ in hits] == ["assign_radiation_boundary_to_objects"]

    def test_describe_lists_subclasses(self, fake_index):
        entry, score = fake_index.search("create_box", top_k=1)[0]
        described = fake_index.describe(entry, score, include_doc=True)
        assert described["available_on_subclasses"] == ["Hfss"]
        assert described["signature"].startswith("create_box(")
        assert "References" in described["docstring"]

    def test_empty_query(self, fake_index):
        assert fake_index.search("  ") == []


class TestIndirectNative:
    def test_native_call_copied_from_helper(self, fake_index):
        # export_csv has no native call of its own; it calls _export_to_csv, which calls
        # odesign.ExportToCsv. That native call should be copied onto export_csv.
        fake_index.ensure_loaded()
        entry = next(e for e in fake_index.entries if e.name == "export_csv")
        assert any("ExportToCsv" in c for c in entry.native_api)
        assert entry.native_indirect and not entry.native_calls
        assert entry.is_indirect

    def test_native_name_rebuilt_from_type_string(self, fake_index):
        # assign_current reaches AssignCurrent only via _create_boundary(.., "Current"),
        # so its native name is rebuilt from the "Current" text. The Boundary.create()
        # method calls AssignCurrent directly and may rank first, so look for the top hit
        # whose native call comes from a helper rather than from the method itself.
        hits = fake_index.search("AssignCurrent", scope="native", top_k=5)
        from_helper = [e for e, _ in hits if e.is_indirect]
        assert from_helper and from_helper[0].name == "assign_current"

    def test_direct_match_ranks_above_helper_match(self, fake_index):
        # The method that literally calls AssignCurrent (Boundary.create) must rank above
        # the method that only reaches it through a helper (assign_current).
        hits = fake_index.search("AssignCurrent", scope="native", top_k=5)
        assert hits and hits[0][0].name == "create"
        assert not hits[0][0].is_indirect

    def test_direct_match_not_flagged_as_helper_match(self, fake_index):
        # A method whose native call is in its docstring/own code must not be flagged
        # as coming from a helper.
        hits = fake_index.search("AssignRadiation", scope="native")
        assert hits and hits[0][0].name == "assign_radiation_boundary_to_objects"
        assert not hits[0][0].is_indirect

    def test_describe_flags_helper_match(self, fake_index):
        # The tool output flags a native call that comes from a helper.
        hits = fake_index.search("AssignCurrent", scope="native", top_k=5)
        entry, score = next((e, s) for e, s in hits if e.name == "assign_current")
        assert fake_index.describe(entry, score).get("native_api_indirect") is True

    def _entry(self, index, qualname_suffix):
        index.ensure_loaded()
        return next(e for e in index.entries if e.qualname.endswith(qualname_suffix))

    def test_type_string_maps_to_exact_native_call(self, fake_index):
        # The keyword form and an ``in (...)`` branch both resolve to the exact call made
        # by Boundary.create, not to a guessed "Assign" + type name.
        entry = self._entry(fake_index, "Hfss.assign_port")
        assert entry.native_dispatch == ["oboundary.AssignWavePort"]

    def test_unknown_type_string_is_ignored(self, fake_index):
        assert self._entry(fake_index, "Hfss.assign_unknown").native_api == []

    def test_classes_never_inherit_helper_calls(self, fake_index):
        fake_index.ensure_loaded()
        assert not [e for e in fake_index.entries if e.kind == "class" and e.is_indirect]

    def test_helper_resolved_on_own_class(self, fake_index):
        # Hfss and Icepak both define _export_to_csv with different native calls; each
        # export_csv must only get the call from its own class.
        hfss = self._entry(fake_index, "Hfss.export_csv")
        icepak = self._entry(fake_index, "Icepak.export_csv")
        assert hfss.native_api == ["odesign.ExportToCsv"]
        assert icepak.native_api == ["odesign.ExportFieldsSummary"]

    def test_helper_chain_through_base_class(self, fake_index):
        # export_report -> _export_report_outer (on Hfss) -> _export_report_inner (only
        # defined on the base class Modeler) -> omodule.ExportReport.
        entry = self._entry(fake_index, "Hfss.export_report")
        assert entry.native_api == ["omodule.ExportReport"]

    def test_generic_and_dunder_calls_are_not_copied(self, fake_index):
        # _read_names only calls ChangeProperty and Get*; __getitem__ is not a helper.
        assert self._entry(fake_index, "Hfss.refresh_names").native_api == []


class TestRealPyAEDTIndex:
    def test_maps_native_create_box(self):
        hits = get_api_index().search("oEditor.CreateBox", top_k=3, scope="native")
        assert any(e.name == "create_box" for e, _ in hits)

    def test_finds_assign_current_by_native_name(self):
        # In real pyaedt, assign_current calls _create_boundary(.., "Current") to reach
        # the native AssignCurrent. Searching for that native name must still find it.
        hits = get_api_index().search("AssignCurrent", top_k=5, scope="native")
        assert any(e.name == "assign_current" for e, _ in hits)

    @pytest.mark.parametrize(
        ("query", "method"),
        [
            ("oModule.AssignOpeningBoundary", "assign_free_opening"),
            ("oModule.AssignConductingPlateBoundary", "assign_conducting_plate"),
            ("InsertSphereSetup", "insert_near_field_sphere"),
        ],
    )
    def test_type_string_methods_found_by_native_name(self, query, method):
        # These methods only reach their native call through _create_boundary with a type
        # string whose native name is not "Assign" + the type.
        hits = get_api_index().search(query, top_k=5, scope="native")
        assert any(e.name == method and e.is_indirect for e, _ in hits)

    def test_no_class_gets_helper_calls(self):
        index = get_api_index()
        index.ensure_loaded()
        assert not [e.name for e in index.entries if e.kind == "class" and e.is_indirect]


class TestFindApiTool:
    @pytest.mark.asyncio
    async def test_parallel_queries(self):
        from ansys.aedt.mcp.tools import find_api

        result = json.loads(
            await find_api(
                ["oModule.AssignRadiation", "create_box", "InsertFrequencySweep"], top_k=3
            )
        )
        assert [r["query"] for r in result["results"]] == [
            "oModule.AssignRadiation",
            "create_box",
            "InsertFrequencySweep",
        ]
        assert result["indexed_entries"] > 1000
        for block in result["results"]:
            assert 0 < block["hit_count"] <= 3
            assert "docstring" not in block["hits"][0]
        assert result["results"][1]["hits"][0]["name"] == "create_box"

    @pytest.mark.asyncio
    async def test_rejects_too_many_queries(self):
        from ansys.aedt.mcp.tools import find_api

        result = await find_api([f"q{i}" for i in range(11)])
        assert "at most 10 queries" in result

    @pytest.mark.asyncio
    async def test_rejects_empty_and_invalid(self):
        from ansys.aedt.mcp.tools import find_api

        assert "at least one" in await find_api(["", "  "])
        assert "top_k" in await find_api(["box"], top_k=0)

    @pytest.mark.asyncio
    async def test_accepts_single_string(self):
        from ansys.aedt.mcp.tools import find_api

        result = json.loads(await find_api("create_box", top_k=1, include_docstring=True))
        assert len(result["results"]) == 1
        assert "docstring" in result["results"][0]["hits"][0]
