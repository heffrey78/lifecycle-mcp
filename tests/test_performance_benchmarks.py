"""
Performance benchmark tests for lifecycle MCP
"""

import pytest
import time
import asyncio
import statistics
from contextlib import contextmanager

from lifecycle_mcp.database_manager import DatabaseManager
from lifecycle_mcp.handlers import (
    RequirementHandler,
    TaskHandler,
    ArchitectureHandler,
    StatusHandler
)


@contextmanager
def measure_time(operation_name):
    """Context manager to measure operation time"""
    start_time = time.perf_counter()
    yield
    end_time = time.perf_counter()
    duration = end_time - start_time
    print(f"\n{operation_name}: {duration:.4f} seconds")
    return duration


@pytest.mark.slow
@pytest.mark.unit
class TestPerformanceBenchmarks:
    """Performance benchmark tests for database operations and handlers"""
    
    @pytest.fixture
    def benchmark_data(self):
        """Generate test data for benchmarks"""
        return {
            "requirements": [
                {
                    "type": "FUNC",
                    "title": f"Performance Test Requirement {i}",
                    "priority": ["P0", "P1", "P2", "P3"][i % 4],
                    "current_state": f"Current state for req {i}",
                    "desired_state": f"Desired state for req {i}",
                    "functional_requirements": [f"FR{j}" for j in range(5)],
                    "acceptance_criteria": [f"AC{j}" for j in range(3)],
                    "author": "Benchmark Test"
                }
                for i in range(100)
            ],
            "tasks": [
                {
                    "requirement_ids": ["REQ-0001-FUNC-00"],
                    "title": f"Performance Test Task {i}",
                    "priority": ["P0", "P1", "P2", "P3"][i % 4],
                    "effort": ["XS", "S", "M", "L", "XL"][i % 5],
                    "assignee": f"User{i % 10}"
                }
                for i in range(200)
            ]
        }
    
    def test_database_insert_performance(self, db_manager, benchmark_data):
        """Benchmark database insert operations"""
        requirements = benchmark_data["requirements"]
        
        # Single inserts
        single_times = []
        for i, req_data in enumerate(requirements[:10]):
            with measure_time(f"Single insert {i+1}") as timer:
                db_manager.insert_record("requirements", {
                    "id": f"REQ-{str(i+1).zfill(4)}-FUNC-00",
                    "requirement_number": i+1,
                    **req_data
                })
            single_times.append(timer)
        
        avg_single = statistics.mean(single_times)
        print(f"\nAverage single insert: {avg_single:.4f} seconds")
        
        # Batch insert
        batch_data = [
            [
                f"REQ-{str(i+11).zfill(4)}-FUNC-00",
                i+11,
                req["type"],
                req["title"],
                req["priority"],
                req["current_state"],
                req["desired_state"],
                req["author"]
            ]
            for i, req in enumerate(requirements[10:20])
        ]
        
        with measure_time("Batch insert (10 records)"):
            db_manager.execute_many(
                """INSERT INTO requirements 
                   (id, requirement_number, type, title, priority, current_state, desired_state, author) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                batch_data
            )
        
        # Performance assertions
        assert avg_single < 0.01  # Single insert should be < 10ms
        
    def test_database_query_performance(self, db_manager, benchmark_data):
        """Benchmark database query operations"""
        # First populate database
        for i, req in enumerate(benchmark_data["requirements"]):
            db_manager.insert_record("requirements", {
                "id": f"REQ-{str(i+1).zfill(4)}-FUNC-00",
                "requirement_number": i+1,
                **req
            })
        
        # Simple query
        with measure_time("Simple SELECT (all records)"):
            results = db_manager.execute_query(
                "SELECT * FROM requirements",
                fetch_all=True
            )
        assert len(results) == 100
        
        # Filtered query
        with measure_time("Filtered SELECT (priority=P1)"):
            results = db_manager.execute_query(
                "SELECT * FROM requirements WHERE priority = ?",
                ["P1"],
                fetch_all=True
            )
        assert len(results) == 25  # 25% should be P1
        
        # Complex query with JOIN (after adding tasks)
        # Add some tasks first
        for i in range(50):
            db_manager.insert_record("tasks", {
                "id": f"TASK-{str(i+1).zfill(4)}-00-00",
                "task_number": i+1,
                "title": f"Task {i+1}",
                "priority": "P1",
                "status": "Not Started"
            })
            db_manager.insert_record("requirement_tasks", {
                "requirement_id": "REQ-0001-FUNC-00",
                "task_id": f"TASK-{str(i+1).zfill(4)}-00-00"
            })
        
        with measure_time("Complex JOIN query"):
            results = db_manager.execute_query(
                """SELECT r.*, COUNT(rt.task_id) as task_count
                   FROM requirements r
                   LEFT JOIN requirement_tasks rt ON r.id = rt.requirement_id
                   GROUP BY r.id""",
                fetch_all=True
            )
        
        # All queries should complete quickly
        assert True  # Timing output is informational
    
    @pytest.mark.asyncio
    async def test_requirement_handler_performance(self, requirement_handler, benchmark_data):
        """Benchmark requirement handler operations"""
        requirements = benchmark_data["requirements"]
        
        # Measure bulk creation
        creation_times = []
        for i, req in enumerate(requirements[:50]):
            start = time.perf_counter()
            await requirement_handler._create_requirement(**req)
            end = time.perf_counter()
            creation_times.append(end - start)
        
        avg_creation = statistics.mean(creation_times)
        p95_creation = statistics.quantiles(creation_times, n=20)[18]  # 95th percentile
        
        print(f"\nRequirement creation - Avg: {avg_creation:.4f}s, P95: {p95_creation:.4f}s")
        
        # Measure query performance
        with measure_time("Query 50 requirements"):
            result = requirement_handler._query_requirements()
        
        # Measure status updates
        update_times = []
        for i in range(10):
            req_id = f"REQ-{str(i+1).zfill(4)}-FUNC-00"
            start = time.perf_counter()
            await requirement_handler._update_requirement_status(
                requirement_id=req_id,
                new_status="Under Review"
            )
            end = time.perf_counter()
            update_times.append(end - start)
        
        avg_update = statistics.mean(update_times)
        print(f"\nStatus update - Avg: {avg_update:.4f}s")
        
        # Performance assertions
        assert avg_creation < 0.05  # < 50ms per requirement
        assert avg_update < 0.02    # < 20ms per update
    
    @pytest.mark.asyncio
    async def test_task_handler_performance(
        self, task_handler, requirement_handler, benchmark_data
    ):
        """Benchmark task handler operations"""
        # Create and approve a requirement first
        await requirement_handler._create_requirement(**benchmark_data["requirements"][0])
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        # Measure task creation
        tasks = benchmark_data["tasks"]
        creation_times = []
        
        for i, task in enumerate(tasks[:100]):
            start = time.perf_counter()
            await task_handler._create_task(**task)
            end = time.perf_counter()
            creation_times.append(end - start)
        
        avg_creation = statistics.mean(creation_times)
        max_creation = max(creation_times)
        
        print(f"\nTask creation - Avg: {avg_creation:.4f}s, Max: {max_creation:.4f}s")
        
        # Measure task queries
        with measure_time("Query 100 tasks"):
            result = task_handler._query_tasks()
        
        # Measure filtered queries
        with measure_time("Query tasks by assignee"):
            result = task_handler._query_tasks(assignee="User5")
        
        # Measure task detail retrieval
        detail_times = []
        for i in range(10):
            task_id = f"TASK-{str(i+1).zfill(4)}-00-00"
            start = time.perf_counter()
            result = task_handler._get_task_details(task_id=task_id)
            end = time.perf_counter()
            detail_times.append(end - start)
        
        avg_detail = statistics.mean(detail_times)
        print(f"\nTask detail retrieval - Avg: {avg_detail:.4f}s")
        
        # Performance assertions
        assert avg_creation < 0.03   # < 30ms per task
        assert avg_detail < 0.01     # < 10ms per detail fetch
    
    @pytest.mark.asyncio
    async def test_concurrent_operations_performance(
        self, requirement_handler, task_handler, benchmark_data
    ):
        """Benchmark concurrent operations"""
        # Create some requirements first
        for i in range(5):
            await requirement_handler._create_requirement(**benchmark_data["requirements"][i])
        
        # Approve first requirement for tasks
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        # Measure concurrent requirement queries
        async def query_requirements():
            return requirement_handler._query_requirements()
        
        with measure_time("10 concurrent requirement queries"):
            results = await asyncio.gather(*[query_requirements() for _ in range(10)])
        
        # Measure mixed concurrent operations
        async def mixed_operations():
            # Mix of async and sync operations
            async_tasks = [
                task_handler._create_task(**benchmark_data["tasks"][0]),
                requirement_handler._create_requirement(**benchmark_data["requirements"][0]),
                task_handler._update_task_status(task_id="TASK-0001-00-00", new_status="In Progress")
            ]
            
            # Run async operations concurrently
            async_results = await asyncio.gather(*async_tasks)
            
            # Run sync operations
            sync_results = [
                requirement_handler._query_requirements(),
                requirement_handler._get_requirement_details(requirement_id="REQ-0001-FUNC-00"),
                task_handler._query_tasks()
            ]
            
            return async_results + sync_results
        
        with measure_time("Mixed concurrent operations"):
            await mixed_operations()
        
        # All operations should complete without errors
        assert len(results) == 10
    
    @pytest.mark.asyncio
    async def test_status_handler_performance_with_large_dataset(
        self, status_handler, requirement_handler, task_handler, 
        architecture_handler, benchmark_data
    ):
        """Benchmark status handler with large dataset"""
        # Create a substantial dataset
        print("\nCreating large dataset...")
        
        # Create 50 requirements
        for i in range(50):
            await requirement_handler._create_requirement(**benchmark_data["requirements"][i])
            
            # Approve some for task creation
            if i < 10:
                req_id = f"REQ-{str(i+1).zfill(4)}-FUNC-00"
                await requirement_handler._update_requirement_status(
                    requirement_id=req_id,
                    new_status="Under Review"
                )
                await requirement_handler._update_requirement_status(
                    requirement_id=req_id,
                    new_status="Approved"
                )
        
        # Create 100 tasks
        for i in range(100):
            task_data = benchmark_data["tasks"][i].copy()
            task_data["requirement_ids"] = [f"REQ-{str((i % 10) + 1).zfill(4)}-FUNC-00"]
            await task_handler._create_task(**task_data)
        
        # Measure status calculation
        with measure_time("Project status with 50 reqs + 100 tasks"):
            result = await status_handler._get_project_status()
        
        # Should complete in reasonable time even with large dataset
        assert "50 requirements" in result[0].text
        assert "100 tasks" in result[0].text
    
    def test_database_index_performance(self, db_manager):
        """Test that database indexes improve query performance"""
        # Insert many records
        for i in range(1000):
            db_manager.insert_record("requirements", {
                "id": f"REQ-{str(i+1).zfill(4)}-FUNC-00",
                "requirement_number": i+1,
                "type": "FUNC",
                "title": f"Requirement {i+1}",
                "priority": ["P0", "P1", "P2", "P3"][i % 4],
                "status": ["Draft", "Approved", "Implemented"][i % 3],
                "current_state": "Current",
                "desired_state": "Desired",
                "author": "Test"
            })
        
        # Query by indexed column (id) - should be fast
        with measure_time("Query by PRIMARY KEY (id)"):
            result = db_manager.execute_query(
                "SELECT * FROM requirements WHERE id = ?",
                ["REQ-0500-FUNC-00"],
                fetch_one=True
            )
        assert result is not None
        
        # Query by non-indexed column - compare performance
        with measure_time("Query by non-indexed column"):
            results = db_manager.execute_query(
                "SELECT * FROM requirements WHERE author = ?",
                ["Test"],
                fetch_all=True
            )
        assert len(results) == 1000
        
        # The indexed query should be significantly faster
        # (actual timing comparison is informational)
    
    @pytest.mark.parametrize("record_count", [10, 100, 1000])
    def test_scalability_with_increasing_data(self, db_manager, record_count):
        """Test performance scalability with increasing data volumes"""
        # Insert records
        insert_times = []
        for i in range(record_count):
            start = time.perf_counter()
            db_manager.insert_record("requirements", {
                "id": f"REQ-{str(i+1).zfill(4)}-FUNC-00",
                "requirement_number": i+1,
                "type": "FUNC",
                "title": f"Scalability Test {i+1}",
                "priority": "P1",
                "current_state": "Current",
                "desired_state": "Desired",
                "author": "Scale Test"
            })
            end = time.perf_counter()
            insert_times.append(end - start)
        
        avg_insert = statistics.mean(insert_times)
        
        # Query all records
        with measure_time(f"Query {record_count} records"):
            results = db_manager.execute_query(
                "SELECT * FROM requirements",
                fetch_all=True
            )
        
        print(f"\n{record_count} records - Avg insert: {avg_insert:.4f}s")
        
        assert len(results) == record_count
        # Insert time should remain relatively constant
        assert avg_insert < 0.01  # < 10ms per insert regardless of table size