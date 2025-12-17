# Project: Todo List API

**Project ID**: todo_api_v11
**Git Branch**: project/todo_api_v11
**Total Tasks**: 5

## Description

Implement a simple but complete REST API for managing todo items. This project demonstrates the multi-task project execution capability of the KnowWhere Agent System.

## Global Requirements

- All code must have type hints
- All functions must have docstrings
- Code must pass mypy type checking
- Use Python 3.11+ features where appropriate
- Follow PEP 8 style guide

## Tasks

### 1. Todo Data Model (`task_1`)

**Priority**: high

Create the core data model for todo items with proper validation. Implement a Pydantic model for Todo items with the following fields: id (unique identifier UUID), title (string, required, max 200 characters), description (optional text), completed (boolean, default False), created_at (timestamp), updated_at (timestamp).

**Requirements**:
- Use Pydantic for validation
- Add proper type hints
- Include docstrings for all fields

### 2. In-Memory Storage (`task_2`)

**Priority**: high
**Dependencies**: `task_1`

Implement a simple in-memory storage system for todos. Create a TodoStorage class that manages todos in memory with basic CRUD operations: create(todo) -> Todo, get(id) -> Optional[Todo], list() -> List[Todo], update(id, data) -> Todo, delete(id) -> bool.

**Requirements**:
- Thread-safe operations
- Raise appropriate exceptions for not found
- Use dictionary for storage

### 3. Create Todo Endpoint (`task_3`)

**Priority**: medium
**Dependencies**: `task_1`, `task_2`

Implement the POST /todos endpoint to create new todos. Add a FastAPI endpoint that accepts todo data in request body, validates the data, creates the todo in storage, and returns the created todo with HTTP 201.

**Requirements**:
- Use FastAPI router
- Proper HTTP status codes
- Error handling for validation errors

### 4. List Todos Endpoint (`task_4`)

**Priority**: medium
**Dependencies**: `task_2`, `task_3`

Implement the GET /todos endpoint to list all todos. Add a FastAPI endpoint that returns all todos, supports optional filtering by completed status, and returns empty list if no todos.

**Requirements**:
- Query parameter: completed (optional boolean)
- Returns HTTP 200
- Proper response model

### 5. Unit Tests (`task_5`)

**Priority**: high
**Dependencies**: `task_1`, `task_2`, `task_3`, `task_4`

Write comprehensive unit tests for all components. Create pytest tests covering Todo model validation, Storage operations, API endpoints (using TestClient), and error cases.

**Requirements**:
- Minimum 80% code coverage
- Test both success and error cases
- Use pytest fixtures
