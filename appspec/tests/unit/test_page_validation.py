"""Tests for page/section validation checks."""

from appspec.models import (
    AppSpec,
    AuthSpec,
    DataField,
    Endpoint,
    EntitySpec,
    FieldType,
    HttpMethod,
    CrudOperation,
    PageLayout,
    PageSection,
    PageSpec,
    SectionType,
    UISpec,
)
from appspec.validation import validate


def _base_spec(**ui_overrides) -> AppSpec:
    """Minimal valid spec with configurable UI pages."""
    ui_kwargs = {
        "framework": "tailwind",
        "pages": [],
    }
    ui_kwargs.update(ui_overrides)
    return AppSpec(
        app_name="Test App",
        slug="test-app",
        auth=AuthSpec(enabled=False),
        entities=[
            EntitySpec(
                name="Task",
                collection="tasks",
                description="A task",
                fields=[
                    DataField(name="title", type=FieldType.STRING, required=True),
                    DataField(
                        name="status",
                        type=FieldType.ENUM,
                        enum_values=["open", "done"],
                        is_filterable=True,
                    ),
                    DataField(name="due_date", type=FieldType.DATETIME, is_sortable=True),
                    DataField(name="priority", type=FieldType.INTEGER),
                ],
            ),
        ],
        endpoints=[
            Endpoint(method=HttpMethod.GET, path="/tasks", entity="Task", operation=CrudOperation.LIST),
        ],
        ui=UISpec(**ui_kwargs),
    )


class TestPageValidationClean:
    def test_no_pages_passes_clean(self):
        result = validate(_base_spec())
        page_issues = [i for i in result.issues if "ui.pages" in i.path]
        assert page_issues == []

    def test_valid_pages_pass_clean(self):
        spec = _base_spec(pages=[
            PageSpec(
                id="dashboard",
                label="Dashboard",
                layout=PageLayout.DASHBOARD,
                is_default=True,
                sections=[
                    PageSection(
                        id="kpi-overview",
                        type=SectionType.KPI_ROW,
                        config={"metrics": [
                            {"label": "Tasks", "data_source": "tasks", "aggregation": "count"},
                        ]},
                        col_span=3,
                    ),
                    PageSection(
                        id="chart-status",
                        type=SectionType.CHART,
                        data_source="tasks",
                        config={"chart_type": "pie", "group_by": "status"},
                    ),
                ],
            ),
            PageSpec(
                id="tasks",
                label="Tasks",
                sections=[
                    PageSection(
                        id="table-tasks",
                        type=SectionType.TABLE,
                        data_source="tasks",
                        config={"columns": ["title", "status"], "default_sort": "due_date"},
                    ),
                ],
            ),
        ])
        result = validate(spec)
        page_issues = [i for i in result.issues if "ui.pages" in i.path]
        assert page_issues == []


class TestDuplicateIDs:
    def test_duplicate_page_ids_error(self):
        spec = _base_spec(pages=[
            PageSpec(id="dup", label="Page 1", is_default=True, sections=[]),
            PageSpec(id="dup", label="Page 2", sections=[]),
        ])
        result = validate(spec)
        errors = [i for i in result.errors if "Duplicate page ID" in i.message]
        assert len(errors) == 1

    def test_duplicate_section_ids_error(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(id="same-id", type=SectionType.TABLE, data_source="tasks"),
            ]),
            PageSpec(id="p2", label="P2", sections=[
                PageSection(id="same-id", type=SectionType.TABLE, data_source="tasks"),
            ]),
        ])
        result = validate(spec)
        errors = [i for i in result.errors if "Duplicate section ID" in i.message]
        assert len(errors) == 1


class TestDefaultPage:
    def test_no_default_page_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=False, sections=[
                PageSection(id="s1", type=SectionType.TABLE, data_source="tasks"),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "is_default" in i.message]
        assert len(warns) == 1

    def test_multiple_default_pages_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(id="s1", type=SectionType.TABLE, data_source="tasks"),
            ]),
            PageSpec(id="p2", label="P2", is_default=True, sections=[
                PageSection(id="s2", type=SectionType.TABLE, data_source="tasks"),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "is_default" in i.message]
        assert len(warns) == 1


class TestOrphanDataSource:
    def test_section_orphan_data_source_error(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(id="s1", type=SectionType.TABLE, data_source="nonexistent"),
            ]),
        ])
        result = validate(spec)
        errors = [i for i in result.errors if "unknown collection" in i.message]
        assert len(errors) == 1
        assert "nonexistent" in errors[0].message


class TestEmptySections:
    def test_page_with_no_sections_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "no sections" in i.message]
        assert len(warns) == 1


class TestChartConfigValidation:
    def test_bad_group_by_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="chart1",
                    type=SectionType.CHART,
                    data_source="tasks",
                    config={"chart_type": "pie", "group_by": "nonexistent_field"},
                ),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "nonexistent_field" in i.message]
        assert len(warns) == 1

    def test_bad_x_field_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="chart1",
                    type=SectionType.CHART,
                    data_source="tasks",
                    config={"chart_type": "line", "x_field": "bad_field"},
                ),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "bad_field" in i.message]
        assert len(warns) == 1

    def test_valid_chart_config_no_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="chart1",
                    type=SectionType.CHART,
                    data_source="tasks",
                    config={"chart_type": "pie", "group_by": "status"},
                ),
            ]),
        ])
        result = validate(spec)
        chart_warns = [i for i in result.warnings if "chart" in i.path.lower() or "group_by" in i.message]
        assert chart_warns == []


class TestTableConfigValidation:
    def test_bad_column_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="t1",
                    type=SectionType.TABLE,
                    data_source="tasks",
                    config={"columns": ["title", "ghost_field"]},
                ),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "ghost_field" in i.message]
        assert len(warns) == 1

    def test_bad_default_sort_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="t1",
                    type=SectionType.TABLE,
                    data_source="tasks",
                    config={"default_sort": "missing_sort_field"},
                ),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "missing_sort_field" in i.message]
        assert len(warns) == 1


class TestKPIConfigValidation:
    def test_bad_kpi_data_source_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="kpi1",
                    type=SectionType.KPI_ROW,
                    config={"metrics": [
                        {"label": "Bad", "data_source": "nonexistent_coll", "aggregation": "count"},
                    ]},
                ),
            ]),
        ])
        result = validate(spec)
        warns = [i for i in result.warnings if "nonexistent_coll" in i.message]
        assert len(warns) == 1

    def test_valid_kpi_no_warning(self):
        spec = _base_spec(pages=[
            PageSpec(id="p1", label="P1", is_default=True, sections=[
                PageSection(
                    id="kpi1",
                    type=SectionType.KPI_ROW,
                    config={"metrics": [
                        {"label": "Tasks", "data_source": "tasks", "aggregation": "count"},
                    ]},
                ),
            ]),
        ])
        result = validate(spec)
        kpi_warns = [i for i in result.warnings if "kpi" in i.path.lower() or "KPI" in i.message]
        assert kpi_warns == []
