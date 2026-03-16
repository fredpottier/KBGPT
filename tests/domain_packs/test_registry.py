# tests/domain_packs/test_registry.py
"""Tests pour le registre des Domain Packs."""

import pytest
from unittest.mock import patch, MagicMock

from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor
from knowbase.domain_packs.registry import PackRegistry


class FakePack(DomainPack):
    """Pack de test."""

    @property
    def name(self) -> str:
        return "fake_pack"

    @property
    def display_name(self) -> str:
        return "Fake Pack"

    @property
    def description(self) -> str:
        return "Pack de test"

    @property
    def priority(self) -> int:
        return 50


class HighPriorityPack(DomainPack):
    """Pack haute priorité pour tests de tri."""

    @property
    def name(self) -> str:
        return "high_priority"

    @property
    def display_name(self) -> str:
        return "High Priority"

    @property
    def description(self) -> str:
        return "Pack haute priorité"

    @property
    def priority(self) -> int:
        return 100


class TestPackRegistry:
    """Tests pour PackRegistry."""

    def test_register_and_list(self):
        registry = PackRegistry()
        pack = FakePack()
        registry.register(pack)

        packs = registry.list_packs()
        assert len(packs) == 1
        assert packs[0].name == "fake_pack"

    def test_get_pack(self):
        registry = PackRegistry()
        pack = FakePack()
        registry.register(pack)

        assert registry.get_pack("fake_pack") is pack
        assert registry.get_pack("nonexistent") is None

    def test_list_sorted_by_priority(self):
        registry = PackRegistry()
        registry.register(FakePack())
        registry.register(HighPriorityPack())

        packs = registry.list_packs()
        assert packs[0].name == "high_priority"
        assert packs[1].name == "fake_pack"

    def test_register_replaces_existing(self):
        registry = PackRegistry()
        registry.register(FakePack())
        registry.register(FakePack())

        packs = registry.list_packs()
        assert len(packs) == 1

    @patch("knowbase.domain_packs.registry.PackRegistry._get_active_pack_names")
    @patch("knowbase.domain_packs.registry.PackRegistry._save_active_pack_names")
    def test_activate_deactivate(self, mock_save, mock_get):
        registry = PackRegistry()
        registry.register(FakePack())

        mock_get.return_value = []
        result = registry.activate("fake_pack", "tenant1")
        assert result is True
        mock_save.assert_called_once_with("tenant1", ["fake_pack"])

    @patch("knowbase.domain_packs.registry.PackRegistry._get_active_pack_names")
    @patch("knowbase.domain_packs.registry.PackRegistry._save_active_pack_names")
    def test_deactivate(self, mock_save, mock_get):
        registry = PackRegistry()
        registry.register(FakePack())

        mock_get.return_value = ["fake_pack"]
        result = registry.deactivate("fake_pack", "tenant1")
        assert result is True
        mock_save.assert_called_once_with("tenant1", [])

    def test_activate_unknown_pack(self):
        registry = PackRegistry()
        result = registry.activate("nonexistent", "tenant1")
        assert result is False

    @patch("knowbase.domain_packs.registry.PackRegistry._get_active_pack_names")
    def test_is_active(self, mock_get):
        registry = PackRegistry()
        registry.register(FakePack())

        mock_get.return_value = ["fake_pack"]
        assert registry.is_active("fake_pack", "tenant1") is True

        mock_get.return_value = []
        assert registry.is_active("fake_pack", "tenant1") is False

    @patch("knowbase.domain_packs.registry.PackRegistry._get_active_pack_names")
    def test_get_active_packs(self, mock_get):
        registry = PackRegistry()
        registry.register(FakePack())
        registry.register(HighPriorityPack())

        mock_get.return_value = ["fake_pack", "high_priority"]
        active = registry.get_active_packs("tenant1")
        assert len(active) == 2
        # Trié par priorité décroissante
        assert active[0].name == "high_priority"

    @patch("knowbase.domain_packs.registry.PackRegistry._get_active_pack_names")
    def test_get_active_packs_missing_pack_ignored(self, mock_get):
        registry = PackRegistry()
        registry.register(FakePack())

        mock_get.return_value = ["fake_pack", "deleted_pack"]
        active = registry.get_active_packs("tenant1")
        assert len(active) == 1
        assert active[0].name == "fake_pack"
