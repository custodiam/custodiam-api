"""Capa de Repository de Custodiam.

Aísla las queries SQLModel del resto de la aplicación. Los servicios
(`app.services.*`) son los únicos consumidores: ni el router ni los
schemas Pydantic deben importar de aquí.

Convención: tres archivos por feature (Repository + Service + Router),
documentada en ADR-013 RBAC + decisiones EN-02-02 (Sprint 4).
"""
