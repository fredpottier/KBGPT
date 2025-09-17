# -*- coding: utf-8 -*-
from importlib import import_module

module = import_module('knowbase.ingestion.pipelines.fill_excel_pipeline')
main = getattr(module, 'main')

if __name__ == '__main__':
    main()
