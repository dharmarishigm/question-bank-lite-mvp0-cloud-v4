output "service_url" { value=google_cloud_run_v2_service.app.uri }
output "database_connection_name" { value=google_sql_database_instance.postgres.connection_name }
output "data_bucket" { value=google_storage_bucket.data.name }
output "service_account" { value=google_service_account.app.email }
