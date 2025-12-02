# Project: Todo List API

## Overview
Implement a simple but complete REST API for managing todo items. This project demonstrates the multi-task project execution capability of the KnowWhere Agent System.

## Features to Implement

### Feature 1: Todo Data Model
Create the core data model for todo items with proper validation.

**Description**: Implement a Pydantic model for Todo items with the following fields:
- id: unique identifier (UUID)
- title: string (required, max 200 characters)
- description: optional text
- completed: boolean (default False)
- created_at: timestamp
- updated_at: timestamp

**Requirements**:
- Use Pydantic for validation
- Add proper type hints
- Include docstrings for all fields

**Priority**: high

### Feature 2: In-Memory Storage
Implement a simple in-memory storage system for todos.

**Description**: Create a TodoStorage class that manages todos in memory with basic CRUD operations:
- create(todo) -> Todo
- get(id) -> Optional[Todo]
- list() -> List[Todo]
- update(id, data) -> Todo
- delete(id) -> bool

**Requirements**:
- Thread-safe operations
- Raise appropriate exceptions for not found
- Use dictionary for storage

**Priority**: high

**Dependencies**: task_1

### Feature 3: Create Todo Endpoint
Implement the POST /todos endpoint to create new todos.

**Description**: Add a FastAPI endpoint that:
- Accepts todo data in request body
- Validates the data
- Creates the todo in storage
- Returns the created todo with HTTP 201

**Requirements**:
- Use FastAPI router
- Proper HTTP status codes
- Error handling for validation errors

**Priority**: medium

**Dependencies**: task_1, task_2

### Feature 4: List Todos Endpoint
Implement the GET /todos endpoint to list all todos.

**Description**: Add a FastAPI endpoint that:
- Returns all todos
- Supports optional filtering by completed status
- Returns empty list if no todos

**Requirements**:
- Query parameter: completed (optional boolean)
- Returns HTTP 200
- Proper response model

**Priority**: medium

**Dependencies**: task_2, task_3

### Feature 5: Unit Tests
Write comprehensive unit tests for all components.

**Description**: Create pytest tests covering:
- Todo model validation
- Storage operations
- API endpoints (using TestClient)
- Error cases

**Requirements**:
- Minimum 80% code coverage
- Test both success and error cases
- Use pytest fixtures

**Priority**: high

**Dependencies**: task_1, task_2, task_3, task_4

## Global Requirements
- All code must have type hints
- All functions must have docstrings
- Code must pass mypy type checking
- Use Python 3.11+ features where appropriate
- Follow PEP 8 style guide
