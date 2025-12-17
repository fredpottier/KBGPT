"""
Tests unitaires complets pour le modele Todo.

Ce module contient des tests exhaustifs couvrant:
- Creation et validation des champs
- Methodes de modification immutable
- Serialisation et deserialisation
- Cas limites et edge cases
- Types invalides et erreurs
"""
import copy
import json
import pytest
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from models import Todo


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def minimal_todo() -> Todo:
    """Fixture: Todo avec seulement le titre requis."""
    return Todo(title="Test todo minimal")


@pytest.fixture
def complete_todo() -> Todo:
    """Fixture: Todo avec tous les champs renseignes."""
    return Todo(
        id=uuid4(),
        title="Test todo complet",
        description="Une description detaillee",
        completed=True,
        created_at=datetime(2024, 1, 15, 10, 30, 0),
        updated_at=datetime(2024, 1, 15, 10, 30, 0),
    )


@pytest.fixture
def todo_factory():
    """Factory fixture pour creer des todos personnalises."""
    def _create_todo(**kwargs) -> Todo:
        defaults = {"title": "Default title"}
        defaults.update(kwargs)
        return Todo(**defaults)
    return _create_todo


@pytest.fixture
def sample_todo_dict() -> dict:
    """Fixture: Dictionnaire valide pour creer un Todo."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "Test depuis dict",
        "description": "Description test",
        "completed": False,
        "created_at": "2024-01-15T10:30:00",
        "updated_at": "2024-01-15T10:30:00",
    }


# =============================================================================
# TESTS DE CREATION
# =============================================================================


@pytest.mark.unit
class TestTodoCreation:
    """Tests pour la creation d'instances Todo."""

    def test_creation_minimal(self, minimal_todo: Todo):
        """Test creation avec seulement le titre."""
        assert minimal_todo.title == "Test todo minimal"
        assert minimal_todo.description is None
        assert minimal_todo.completed is False
        assert isinstance(minimal_todo.id, UUID)
        assert isinstance(minimal_todo.created_at, datetime)
        assert isinstance(minimal_todo.updated_at, datetime)

    def test_creation_complete(self, complete_todo: Todo):
        """Test creation avec tous les champs."""
        assert complete_todo.title == "Test todo complet"
        assert complete_todo.description == "Une description detaillee"
        assert complete_todo.completed is True
        assert complete_todo.created_at == datetime(2024, 1, 15, 10, 30, 0)
        assert complete_todo.updated_at == datetime(2024, 1, 15, 10, 30, 0)

    def test_creation_with_factory(self, todo_factory):
        """Test creation via factory fixture."""
        todo = todo_factory(title="Factory todo", completed=True)
        assert todo.title == "Factory todo"
        assert todo.completed is True

    def test_id_auto_generated_unique(self):
        """Test que chaque todo a un id unique auto-genere."""
        todos = [Todo(title=f"Todo {i}") for i in range(10)]
        ids = [todo.id for todo in todos]
        assert len(set(ids)) == 10, "Tous les IDs doivent etre uniques"

    def test_id_custom_preserved(self):
        """Test qu'un id custom est preserve."""
        custom_id = uuid4()
        todo = Todo(id=custom_id, title="Test")
        assert todo.id == custom_id

    def test_timestamps_auto_generated(self):
        """Test que les timestamps sont generes automatiquement."""
        before = datetime.utcnow()
        todo = Todo(title="Test")
        after = datetime.utcnow()

        assert before <= todo.created_at <= after
        assert before <= todo.updated_at <= after
        # created_at et updated_at sont tres proches a la creation
        delta = abs((todo.updated_at - todo.created_at).total_seconds())
        assert delta < 1, "Timestamps doivent etre tres proches"


# =============================================================================
# TESTS DE VALIDATION DU TITRE
# =============================================================================


@pytest.mark.unit
class TestTodoTitleValidation:
    """Tests pour la validation du champ titre."""

    def test_title_required(self):
        """Test que le titre est obligatoire."""
        with pytest.raises(ValidationError) as exc_info:
            Todo()
        assert "title" in str(exc_info.value)

    @pytest.mark.parametrize("invalid_title,expected_error", [
        ("", "String should have at least 1 character"),
        ("   ", "Le titre ne peut pas etre vide"),
        ("\t\n", "Le titre ne peut pas etre vide"),
    ])
    def test_title_empty_rejected(self, invalid_title: str, expected_error: str):
        """Test que les titres vides sont rejetes."""
        with pytest.raises(ValidationError) as exc_info:
            Todo(title=invalid_title)
        assert expected_error in str(exc_info.value) or "title" in str(exc_info.value)

    def test_title_max_length_valid(self):
        """Test titre de 200 caracteres (max valide)."""
        valid_title = "a" * 200
        todo = Todo(title=valid_title)
        assert len(todo.title) == 200

    def test_title_max_length_exceeded(self):
        """Test titre de 201 caracteres (invalide)."""
        invalid_title = "a" * 201
        with pytest.raises(ValidationError) as exc_info:
            Todo(title=invalid_title)
        assert "at most 200" in str(exc_info.value).lower()

    @pytest.mark.parametrize("title_with_spaces,expected", [
        ("  Test  ", "Test"),
        ("\tTest\t", "Test"),
        ("\n Test \n", "Test"),
        ("  Multiple   Words  ", "Multiple   Words"),
    ])
    def test_title_stripped(self, title_with_spaces: str, expected: str):
        """Test que les espaces externes sont supprimes du titre."""
        todo = Todo(title=title_with_spaces)
        assert todo.title == expected

    def test_title_single_character(self):
        """Test titre d'un seul caractere."""
        todo = Todo(title="X")
        assert todo.title == "X"


# =============================================================================
# TESTS DE VALIDATION DE LA DESCRIPTION
# =============================================================================


@pytest.mark.unit
class TestTodoDescriptionValidation:
    """Tests pour la validation du champ description."""

    def test_description_optional(self, minimal_todo: Todo):
        """Test que la description est optionnelle."""
        assert minimal_todo.description is None

    def test_description_with_value(self, todo_factory):
        """Test description avec une valeur."""
        todo = todo_factory(description="Ma description")
        assert todo.description == "Ma description"

    @pytest.mark.parametrize("empty_desc", [
        "",
        "   ",
        "\t",
        "\n",
        "\t\n  ",
    ])
    def test_description_empty_becomes_none(self, todo_factory, empty_desc: str):
        """Test que les descriptions vides deviennent None."""
        todo = todo_factory(description=empty_desc)
        assert todo.description is None

    @pytest.mark.parametrize("desc_with_spaces,expected", [
        ("  Description  ", "Description"),
        ("\tDescription\t", "Description"),
        ("  Multi word description  ", "Multi word description"),
    ])
    def test_description_stripped(self, todo_factory, desc_with_spaces: str, expected: str):
        """Test que les espaces externes sont supprimes."""
        todo = todo_factory(description=desc_with_spaces)
        assert todo.description == expected

    def test_description_preserves_internal_whitespace(self, todo_factory):
        """Test que les espaces internes sont preserves."""
        desc = "Ligne 1\nLigne 2\n\nLigne 4"
        todo = todo_factory(description=desc)
        assert todo.description == desc
        assert "\n" in todo.description

    def test_description_very_long(self, todo_factory):
        """Test description tres longue (pas de limite)."""
        long_desc = "x" * 100000
        todo = todo_factory(description=long_desc)
        assert len(todo.description) == 100000


# =============================================================================
# TESTS DU CHAMP COMPLETED
# =============================================================================


@pytest.mark.unit
class TestTodoCompletedField:
    """Tests pour le champ completed."""

    def test_completed_default_false(self, minimal_todo: Todo):
        """Test que completed est False par defaut."""
        assert minimal_todo.completed is False

    @pytest.mark.parametrize("value", [True, False])
    def test_completed_boolean_values(self, todo_factory, value: bool):
        """Test avec valeurs booleennes explicites."""
        todo = todo_factory(completed=value)
        assert todo.completed is value

    @pytest.mark.parametrize("truthy_value", [1, "true", "yes", "on", "1"])
    def test_completed_truthy_coercion(self, todo_factory, truthy_value: Any):
        """Test coercion des valeurs truthy vers True."""
        todo = todo_factory(completed=truthy_value)
        assert todo.completed is True

    @pytest.mark.parametrize("falsy_value", [0, "false", "no", "off", "0"])
    def test_completed_falsy_coercion(self, todo_factory, falsy_value: Any):
        """Test coercion des valeurs falsy vers False."""
        todo = todo_factory(completed=falsy_value)
        assert todo.completed is False

    @pytest.mark.parametrize("invalid_bool", ["", "maybe", [], [1], {}])
    def test_completed_invalid_types_rejected(self, invalid_bool: Any):
        """Test que les types invalides pour completed sont rejetes."""
        with pytest.raises(ValidationError):
            Todo(title="Test", completed=invalid_bool)


# =============================================================================
# TESTS DES METHODES
# =============================================================================


@pytest.mark.unit
class TestTodoMethods:
    """Tests pour les methodes du modele Todo."""

    def test_mark_completed_returns_new_instance(self, minimal_todo: Todo):
        """Test que mark_completed retourne une nouvelle instance."""
        completed = minimal_todo.mark_completed()
        assert completed is not minimal_todo
        assert completed.completed is True

    def test_mark_completed_preserves_original(self, minimal_todo: Todo):
        """Test que l'original n'est pas modifie (immutabilite)."""
        original_completed = minimal_todo.completed
        _ = minimal_todo.mark_completed()
        assert minimal_todo.completed == original_completed

    def test_mark_completed_preserves_fields(self, complete_todo: Todo):
        """Test que les autres champs sont preserves."""
        completed = complete_todo.mark_completed()
        assert completed.id == complete_todo.id
        assert completed.title == complete_todo.title
        assert completed.description == complete_todo.description
        assert completed.created_at == complete_todo.created_at

    def test_mark_completed_updates_timestamp(self, minimal_todo: Todo):
        """Test que updated_at est mis a jour."""
        original_updated = minimal_todo.updated_at
        completed = minimal_todo.mark_completed()
        assert completed.updated_at >= original_updated

    def test_mark_incomplete_returns_new_instance(self, complete_todo: Todo):
        """Test que mark_incomplete retourne une nouvelle instance."""
        incomplete = complete_todo.mark_incomplete()
        assert incomplete is not complete_todo
        assert incomplete.completed is False

    def test_mark_incomplete_preserves_original(self, complete_todo: Todo):
        """Test que l'original n'est pas modifie."""
        original_completed = complete_todo.completed
        _ = complete_todo.mark_incomplete()
        assert complete_todo.completed == original_completed

    def test_mark_incomplete_updates_timestamp(self, complete_todo: Todo):
        """Test que updated_at est mis a jour."""
        original_updated = complete_todo.updated_at
        incomplete = complete_todo.mark_incomplete()
        assert incomplete.updated_at >= original_updated


@pytest.mark.unit
class TestTodoUpdateMethod:
    """Tests specifiques pour la methode update()."""

    def test_update_title_only(self, minimal_todo: Todo):
        """Test mise a jour du titre seul."""
        updated = minimal_todo.update(title="Nouveau titre")
        assert updated.title == "Nouveau titre"
        assert updated.description == minimal_todo.description
        assert updated.completed == minimal_todo.completed

    def test_update_description_only(self, minimal_todo: Todo):
        """Test mise a jour de la description seule."""
        updated = minimal_todo.update(description="Nouvelle desc")
        assert updated.description == "Nouvelle desc"
        assert updated.title == minimal_todo.title

    def test_update_completed_only(self, minimal_todo: Todo):
        """Test mise a jour du statut seul."""
        updated = minimal_todo.update(completed=True)
        assert updated.completed is True
        assert updated.title == minimal_todo.title

    def test_update_multiple_fields(self, minimal_todo: Todo):
        """Test mise a jour de plusieurs champs."""
        updated = minimal_todo.update(
            title="Nouveau",
            description="Nouvelle desc",
            completed=True
        )
        assert updated.title == "Nouveau"
        assert updated.description == "Nouvelle desc"
        assert updated.completed is True

    def test_update_no_changes(self, minimal_todo: Todo):
        """Test update sans arguments met a jour seulement updated_at."""
        original_updated = minimal_todo.updated_at
        updated = minimal_todo.update()
        assert updated.title == minimal_todo.title
        assert updated.updated_at >= original_updated

    def test_update_preserves_immutability(self, minimal_todo: Todo):
        """Test que update preserve l'immutabilite."""
        original_title = minimal_todo.title
        _ = minimal_todo.update(title="Changed")
        assert minimal_todo.title == original_title

    def test_update_preserves_id(self, minimal_todo: Todo):
        """Test que l'id est toujours preserve."""
        updated = minimal_todo.update(title="Nouveau")
        assert updated.id == minimal_todo.id

    def test_update_chain(self, minimal_todo: Todo):
        """Test chainages de updates."""
        result = (
            minimal_todo
            .update(title="Step 1")
            .update(description="Step 2")
            .update(completed=True)
        )
        assert result.title == "Step 1"
        assert result.description == "Step 2"
        assert result.completed is True


# =============================================================================
# TESTS DE SERIALISATION
# =============================================================================


@pytest.mark.unit
class TestTodoSerialization:
    """Tests pour la serialisation/deserialisation."""

    def test_model_dump(self, complete_todo: Todo):
        """Test serialisation en dictionnaire."""
        data = complete_todo.model_dump()
        assert isinstance(data, dict)
        assert data["title"] == complete_todo.title
        assert data["description"] == complete_todo.description
        assert data["completed"] == complete_todo.completed
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_model_dump_json(self, complete_todo: Todo):
        """Test serialisation en JSON string."""
        json_str = complete_todo.model_dump_json()
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert data["title"] == complete_todo.title

    def test_model_validate_from_dict(self, sample_todo_dict: dict):
        """Test creation depuis un dictionnaire."""
        todo = Todo.model_validate(sample_todo_dict)
        assert str(todo.id) == sample_todo_dict["id"]
        assert todo.title == sample_todo_dict["title"]
        assert todo.description == sample_todo_dict["description"]

    def test_model_validate_json(self, complete_todo: Todo):
        """Test roundtrip JSON complet."""
        json_str = complete_todo.model_dump_json()
        restored = Todo.model_validate_json(json_str)
        assert restored.id == complete_todo.id
        assert restored.title == complete_todo.title
        assert restored.description == complete_todo.description
        assert restored.completed == complete_todo.completed

    def test_roundtrip_preserves_all_fields(self, complete_todo: Todo):
        """Test que le roundtrip preserve tous les champs."""
        data = complete_todo.model_dump()
        restored = Todo.model_validate(data)
        assert restored.id == complete_todo.id
        assert restored.title == complete_todo.title
        assert restored.description == complete_todo.description
        assert restored.completed == complete_todo.completed
        assert restored.created_at == complete_todo.created_at
        assert restored.updated_at == complete_todo.updated_at

    def test_json_schema_has_example(self):
        """Test que le schema JSON contient un exemple."""
        schema = Todo.model_json_schema()
        # L'exemple peut etre dans 'example' ou 'examples'
        assert "example" in schema or "examples" in schema


# =============================================================================
# TESTS DES TYPES INVALIDES
# =============================================================================


@pytest.mark.unit
class TestTodoInvalidTypes:
    """Tests avec des types invalides."""

    @pytest.mark.parametrize("invalid_title", [
        None,
        123,
        12.5,
        ["list"],
        {"dict": "value"},
        True,
    ])
    def test_title_invalid_types(self, invalid_title: Any):
        """Test que les types non-string pour title sont rejetes ou convertis."""
        if invalid_title is None:
            with pytest.raises(ValidationError):
                Todo(title=invalid_title)
        else:
            # Pydantic peut convertir certains types en string
            try:
                todo = Todo(title=invalid_title)
                assert isinstance(todo.title, str)
            except ValidationError:
                pass  # Certains types peuvent etre rejetes

    @pytest.mark.parametrize("invalid_id", [
        "not-a-uuid",
        123,
        "12345678-1234-1234-1234-123456789xyz",  # UUID invalide
    ])
    def test_id_invalid_values(self, invalid_id: Any):
        """Test que les IDs invalides sont rejetes."""
        with pytest.raises(ValidationError):
            Todo(id=invalid_id, title="Test")

    def test_invalid_datetime(self):
        """Test que les datetimes invalides sont rejetees."""
        with pytest.raises(ValidationError):
            Todo(title="Test", created_at="not-a-date")


# =============================================================================
# TESTS DES CAS LIMITES
# =============================================================================


@pytest.mark.unit
class TestTodoEdgeCases:
    """Tests pour les cas limites."""

    def test_unicode_title(self, todo_factory):
        """Test titre avec caracteres unicode."""
        unicode_title = "Tache avec accents: e, a, u, c et chinois"
        todo = todo_factory(title=unicode_title)
        assert todo.title == unicode_title

    def test_unicode_description(self, todo_factory):
        """Test description avec emojis et caracteres speciaux."""
        todo = todo_factory(description="Description avec accents et symboles")
        assert todo.description is not None

    def test_special_characters_in_title(self, todo_factory):
        """Test titre avec caracteres speciaux."""
        special_title = "Test <>&\"'\\n\\t!@#$%^&*()"
        todo = todo_factory(title=special_title)
        assert todo.title == special_title

    def test_sql_injection_like_title(self, todo_factory):
        """Test titre ressemblant a une injection SQL."""
        sql_title = "'; DROP TABLE todos; --"
        todo = todo_factory(title=sql_title)
        assert todo.title == sql_title

    def test_html_in_description(self, todo_factory):
        """Test description avec HTML."""
        html_desc = "<script>alert('xss')</script>"
        todo = todo_factory(description=html_desc)
        assert todo.description == html_desc

    def test_multiline_description(self, todo_factory):
        """Test description multilignes."""
        multiline = "Ligne 1\nLigne 2\r\nLigne 3\n\nLigne 5"
        todo = todo_factory(description=multiline)
        assert todo.description == multiline
        assert todo.description.count("\n") == 4

    def test_title_exactly_at_boundary(self, todo_factory):
        """Test titre exactement a la limite (200 chars)."""
        exact_title = "x" * 200
        todo = todo_factory(title=exact_title)
        assert len(todo.title) == 200

    def test_title_one_over_boundary(self):
        """Test titre un caractere au-dessus de la limite."""
        over_title = "x" * 201
        with pytest.raises(ValidationError):
            Todo(title=over_title)


# =============================================================================
# TESTS DE COPIE ET EGALITE
# =============================================================================


@pytest.mark.unit
class TestTodoCopyAndEquality:
    """Tests pour la copie et comparaison d'objets."""

    def test_model_copy(self, complete_todo: Todo):
        """Test copie avec model_copy."""
        copied = complete_todo.model_copy()
        assert copied is not complete_todo
        assert copied.id == complete_todo.id
        assert copied.title == complete_todo.title

    def test_model_copy_with_update(self, complete_todo: Todo):
        """Test copie avec modification."""
        copied = complete_todo.model_copy(update={"title": "Modifie"})
        assert copied.title == "Modifie"
        assert complete_todo.title == "Test todo complet"

    def test_deep_copy(self, complete_todo: Todo):
        """Test copie profonde."""
        copied = copy.deepcopy(complete_todo)
        assert copied is not complete_todo
        assert copied.id == complete_todo.id

    def test_equality_same_id(self, complete_todo: Todo):
        """Test egalite basee sur les valeurs."""
        copied = complete_todo.model_copy()
        assert copied == complete_todo

    def test_equality_different_todos(self, todo_factory):
        """Test inegalite de todos differents."""
        todo1 = todo_factory(title="Todo 1")
        todo2 = todo_factory(title="Todo 2")
        assert todo1 != todo2

    def test_hash_not_supported_by_default(self, complete_todo: Todo):
        """Test que les modeles Pydantic ne sont pas hashables par defaut."""
        # Les modeles Pydantic v2 ne sont pas hashables par defaut
        with pytest.raises(TypeError):
            hash(complete_todo)


# =============================================================================
# TESTS DE VALIDATION DEPUIS DICT
# =============================================================================


@pytest.mark.unit
class TestTodoFromDict:
    """Tests pour la creation depuis des dictionnaires."""

    def test_from_dict_minimal(self):
        """Test creation depuis dict minimal."""
        data = {"title": "From dict"}
        todo = Todo.model_validate(data)
        assert todo.title == "From dict"

    def test_from_dict_with_extra_fields(self):
        """Test que les champs extra sont ignores par defaut."""
        data = {
            "title": "Test",
            "extra_field": "should be ignored",
            "another_extra": 123,
        }
        todo = Todo.model_validate(data)
        assert todo.title == "Test"
        assert not hasattr(todo, "extra_field")

    def test_from_dict_missing_required(self):
        """Test erreur si champ requis manquant."""
        data = {"description": "No title"}
        with pytest.raises(ValidationError) as exc_info:
            Todo.model_validate(data)
        assert "title" in str(exc_info.value)

    def test_from_dict_uuid_as_string(self):
        """Test que l'UUID peut etre fourni comme string."""
        data = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "title": "Test",
        }
        todo = Todo.model_validate(data)
        assert isinstance(todo.id, UUID)
        assert str(todo.id) == "550e8400-e29b-41d4-a716-446655440000"

    def test_from_dict_datetime_as_string(self):
        """Test que les datetimes peuvent etre fournies comme strings."""
        data = {
            "title": "Test",
            "created_at": "2024-01-15T10:30:00",
            "updated_at": "2024-01-15T10:30:00Z",
        }
        todo = Todo.model_validate(data)
        assert isinstance(todo.created_at, datetime)
        assert isinstance(todo.updated_at, datetime)


# =============================================================================
# TESTS DE PERFORMANCE
# =============================================================================


@pytest.mark.unit
class TestTodoPerformance:
    """Tests de performance basiques."""

    def test_creation_performance(self):
        """Test que la creation de nombreux todos est rapide."""
        start = datetime.utcnow()
        todos = [Todo(title=f"Todo {i}") for i in range(1000)]
        duration = (datetime.utcnow() - start).total_seconds()
        assert len(todos) == 1000
        assert duration < 5, f"Creation trop lente: {duration}s"

    def test_serialization_performance(self, complete_todo: Todo):
        """Test que la serialisation est rapide."""
        start = datetime.utcnow()
        for _ in range(1000):
            _ = complete_todo.model_dump_json()
        duration = (datetime.utcnow() - start).total_seconds()
        assert duration < 5, f"Serialisation trop lente: {duration}s"

    def test_update_performance(self, minimal_todo: Todo):
        """Test que les updates sont rapides."""
        todo = minimal_todo
        start = datetime.utcnow()
        for i in range(1000):
            todo = todo.update(title=f"Title {i}")
        duration = (datetime.utcnow() - start).total_seconds()
        assert duration < 5, f"Updates trop lents: {duration}s"
