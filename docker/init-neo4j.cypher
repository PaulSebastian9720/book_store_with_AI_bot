// LangGraph Planner - State Machine for Bookstore Orchestrator
// Nodos representan estados del planner
// Relaciones TRANSITION representan transiciones entre estados

// Crear nodos de estado
CREATE (vi:State {name: 'VALIDATE_INPUT', description: 'Valida datos de entrada del usuario'})
CREATE (lc:State {name: 'LOAD_CONTEXT', description: 'Carga contexto desde la base de datos'})
CREATE (aa:State {name: 'APPLY_ACTION', description: 'Ejecuta la acción semántica seleccionada'})
CREATE (pe:State {name: 'PERSIST', description: 'Persiste cambios en la base de datos'})
CREATE (br:State {name: 'BUILD_RESPONSE', description: 'Construye respuesta natural con LLM'})
CREATE (dn:State {name: 'DONE', description: 'Estado terminal - flujo completado'})
CREATE (ai:State {name: 'ASK_INPUT', description: 'Solicita datos faltantes al usuario'})

// Transiciones del flujo principal
CREATE (vi)-[:TRANSITION {condition: 'valid_input'}]->(lc)
CREATE (vi)-[:TRANSITION {condition: 'missing_data'}]->(ai)
CREATE (ai)-[:TRANSITION {condition: 'user_responded'}]->(vi)
CREATE (lc)-[:TRANSITION {condition: 'context_loaded'}]->(aa)
CREATE (aa)-[:TRANSITION {condition: 'action_completed'}]->(pe)
CREATE (aa)-[:TRANSITION {condition: 'action_failed'}]->(br)
CREATE (pe)-[:TRANSITION {condition: 'persisted'}]->(br)
CREATE (br)-[:TRANSITION {condition: 'response_built'}]->(dn)

// Índice para búsqueda rápida
CREATE INDEX state_name IF NOT EXISTS FOR (s:State) ON (s.name);
