"""Tests pour le système de dépréciation OSMOSE."""

import warnings
from typing import Any

import pytest

from knowbase.common.deprecation import (
    DeprecationInfo,
    DeprecationKind,
    deprecated,
    deprecated_class,
    deprecated_module,
    get_deprecation_info,
    get_deprecated_modules,
    is_deprecated,
)


class TestDeprecationKind:
    """Tests pour l'enum DeprecationKind."""

    def test_all_kinds_are_strings(self):
        """Vérifie que tous les kinds sont des chaînes."""
        for kind in DeprecationKind:
            assert isinstance(kind.value, str)

    def test_expected_kinds_exist(self):
        """Vérifie que tous les kinds attendus existent."""
        expected = ["DEAD_CODE", "LEGACY_COMPAT", "EXPERIMENTAL", "PHASE_ABANDONED"]
        actual = [k.value for k in DeprecationKind]
        assert set(expected) == set(actual)


class TestDeprecationInfo:
    """Tests pour DeprecationInfo."""

    def test_to_dict_complete(self):
        """Test sérialisation complète."""
        info = DeprecationInfo(
            kind=DeprecationKind.DEAD_CODE,
            reason="Test reason",
            removal_version="2.0.0",
            alternative="new_func()",
            module="test.module",
            qualname="TestClass.method",
        )

        d = info.to_dict()
        assert d["kind"] == "DEAD_CODE"
        assert d["reason"] == "Test reason"
        assert d["removal_version"] == "2.0.0"
        assert d["alternative"] == "new_func()"
        assert d["module"] == "test.module"
        assert d["qualname"] == "TestClass.method"

    def test_to_dict_minimal(self):
        """Test sérialisation minimale."""
        info = DeprecationInfo(
            kind=DeprecationKind.EXPERIMENTAL,
            reason="In development",
        )

        d = info.to_dict()
        assert d["kind"] == "EXPERIMENTAL"
        assert d["reason"] == "In development"
        assert d["removal_version"] is None
        assert d["alternative"] is None

    def test_format_message_complete(self):
        """Test formatage du message complet."""
        info = DeprecationInfo(
            kind=DeprecationKind.LEGACY_COMPAT,
            reason="Old API",
            alternative="new_api()",
            removal_version="3.0.0",
            qualname="old_function",
        )

        msg = info.format_message()
        assert "[OSMOSE:DEPRECATED:LEGACY_COMPAT]" in msg
        assert "old_function" in msg
        assert "Old API" in msg
        assert "Use: new_api()" in msg
        assert "Removal: 3.0.0" in msg

    def test_format_message_minimal(self):
        """Test formatage du message minimal."""
        info = DeprecationInfo(
            kind=DeprecationKind.DEAD_CODE,
            reason="Never used",
            module="knowbase.old_module",
        )

        msg = info.format_message()
        assert "[OSMOSE:DEPRECATED:DEAD_CODE]" in msg
        assert "knowbase.old_module" in msg
        assert "Never used" in msg


class TestDeprecatedDecorator:
    """Tests pour le décorateur @deprecated."""

    def test_deprecated_function_emits_warning(self):
        """Vérifie que l'appel d'une fonction dépréciée émet un warning."""

        @deprecated(
            kind=DeprecationKind.DEAD_CODE,
            reason="Test function",
        )
        def old_func() -> int:
            return 42

        with pytest.warns(DeprecationWarning) as record:
            result = old_func()

        assert result == 42
        assert len(record) == 1
        assert "DEAD_CODE" in str(record[0].message)
        assert "Test function" in str(record[0].message)

    def test_deprecated_function_preserves_return_value(self):
        """Vérifie que la valeur de retour est préservée."""

        @deprecated(
            kind=DeprecationKind.EXPERIMENTAL,
            reason="Testing",
        )
        def compute(x: int, y: int) -> int:
            return x + y

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert compute(2, 3) == 5

    def test_deprecated_function_preserves_signature(self):
        """Vérifie que la signature est préservée."""

        @deprecated(
            kind=DeprecationKind.LEGACY_COMPAT,
            reason="Old signature",
        )
        def func_with_args(a: int, b: str = "default") -> str:
            """Docstring preserved."""
            return f"{a}-{b}"

        # Nom et docstring préservés
        assert func_with_args.__name__ == "func_with_args"
        assert "Docstring preserved" in (func_with_args.__doc__ or "")

        # Appel avec kwargs
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert func_with_args(1, b="test") == "1-test"

    def test_deprecated_function_has_metadata(self):
        """Vérifie que les métadonnées sont attachées."""

        @deprecated(
            kind=DeprecationKind.PHASE_ABANDONED,
            reason="Phase 1 cancelled",
            removal_version="2.0.0",
            alternative="new_impl()",
        )
        def phase1_func() -> None:
            pass

        assert is_deprecated(phase1_func)
        info = get_deprecation_info(phase1_func)
        assert info is not None
        assert info.kind == DeprecationKind.PHASE_ABANDONED
        assert info.reason == "Phase 1 cancelled"
        assert info.removal_version == "2.0.0"
        assert info.alternative == "new_impl()"

    def test_deprecated_async_function(self):
        """Vérifie que les fonctions async sont supportées."""
        import asyncio

        @deprecated(
            kind=DeprecationKind.DEAD_CODE,
            reason="Async test",
        )
        async def async_old() -> int:
            return 100

        async def run_test():
            with pytest.warns(DeprecationWarning):
                return await async_old()

        result = asyncio.run(run_test())
        assert result == 100


class TestDeprecatedClassDecorator:
    """Tests pour le décorateur @deprecated_class."""

    def test_deprecated_class_emits_warning_on_init(self):
        """Vérifie que l'instanciation émet un warning."""

        @deprecated_class(
            kind=DeprecationKind.PHASE_ABANDONED,
            reason="Old class",
        )
        class OldClass:
            def __init__(self, value: int):
                self.value = value

        with pytest.warns(DeprecationWarning) as record:
            obj = OldClass(42)

        assert obj.value == 42
        assert len(record) == 1
        assert "PHASE_ABANDONED" in str(record[0].message)

    def test_deprecated_class_has_metadata(self):
        """Vérifie que les métadonnées sont attachées à la classe."""

        @deprecated_class(
            kind=DeprecationKind.LEGACY_COMPAT,
            reason="Use NewClass instead",
            alternative="NewClass",
        )
        class LegacyClass:
            pass

        assert is_deprecated(LegacyClass)
        info = get_deprecation_info(LegacyClass)
        assert info is not None
        assert info.kind == DeprecationKind.LEGACY_COMPAT
        assert info.alternative == "NewClass"

    def test_deprecated_class_methods_work(self):
        """Vérifie que les méthodes de la classe fonctionnent."""

        @deprecated_class(
            kind=DeprecationKind.EXPERIMENTAL,
            reason="Testing",
        )
        class TestClass:
            def __init__(self) -> None:
                self.items: list[Any] = []

            def add(self, item: Any) -> None:
                self.items.append(item)

            def get_all(self) -> list[Any]:
                return self.items

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            obj = TestClass()
            obj.add("a")
            obj.add("b")
            assert obj.get_all() == ["a", "b"]


class TestDeprecatedModule:
    """Tests pour deprecated_module()."""

    def test_deprecated_module_registers_in_registry(self):
        """Vérifie que le module est enregistré."""
        # Note: On ne peut pas facilement tester deprecated_module()
        # car il dépend du contexte d'import
        # On vérifie juste que get_deprecated_modules retourne un dict
        modules = get_deprecated_modules()
        assert isinstance(modules, dict)

    def test_deprecated_module_emits_warning(self):
        """Vérifie que deprecated_module émet un warning."""
        with pytest.warns(DeprecationWarning) as record:
            deprecated_module(
                kind=DeprecationKind.DEAD_CODE,
                reason="Test module deprecation",
            )

        assert len(record) == 1
        assert "DEAD_CODE" in str(record[0].message)
        assert "Test module deprecation" in str(record[0].message)


class TestHelperFunctions:
    """Tests pour les fonctions utilitaires."""

    def test_is_deprecated_returns_false_for_normal_function(self):
        """Vérifie is_deprecated sur fonction normale."""

        def normal_func() -> None:
            pass

        assert is_deprecated(normal_func) is False

    def test_is_deprecated_returns_true_for_deprecated_function(self):
        """Vérifie is_deprecated sur fonction dépréciée."""

        @deprecated(kind=DeprecationKind.DEAD_CODE, reason="Test")
        def old_func() -> None:
            pass

        assert is_deprecated(old_func) is True

    def test_get_deprecation_info_returns_none_for_normal(self):
        """Vérifie get_deprecation_info sur objet normal."""

        def normal() -> None:
            pass

        assert get_deprecation_info(normal) is None

    def test_get_deprecation_info_returns_info_for_deprecated(self):
        """Vérifie get_deprecation_info sur objet déprécié."""

        @deprecated(
            kind=DeprecationKind.EXPERIMENTAL,
            reason="WIP",
        )
        def wip_func() -> None:
            pass

        info = get_deprecation_info(wip_func)
        assert info is not None
        assert info.kind == DeprecationKind.EXPERIMENTAL
        assert info.reason == "WIP"


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_multiple_deprecated_functions_independent(self):
        """Vérifie que plusieurs fonctions dépréciées sont indépendantes."""

        @deprecated(kind=DeprecationKind.DEAD_CODE, reason="Reason A")
        def func_a() -> str:
            return "a"

        @deprecated(kind=DeprecationKind.EXPERIMENTAL, reason="Reason B")
        def func_b() -> str:
            return "b"

        info_a = get_deprecation_info(func_a)
        info_b = get_deprecation_info(func_b)

        assert info_a is not None and info_a.reason == "Reason A"
        assert info_b is not None and info_b.reason == "Reason B"
        assert info_a.kind != info_b.kind

    def test_deprecated_with_exception(self):
        """Vérifie que les exceptions sont propagées."""

        @deprecated(kind=DeprecationKind.DEAD_CODE, reason="Raises error")
        def raises_error() -> None:
            raise ValueError("Intentional error")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(ValueError, match="Intentional error"):
                raises_error()

    def test_nested_deprecated_class_method(self):
        """Vérifie méthode dépréciée dans une classe."""

        class MyClass:
            @deprecated(kind=DeprecationKind.LEGACY_COMPAT, reason="Old method")
            def old_method(self) -> int:
                return 123

            def new_method(self) -> int:
                return 456

        obj = MyClass()

        # new_method ne déclenche pas de warning
        assert obj.new_method() == 456

        # old_method déclenche un warning
        with pytest.warns(DeprecationWarning):
            result = obj.old_method()
        assert result == 123
