from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, TYPE_CHECKING

from clang.cindex import TokenKind, Cursor

from .lpg import Node, Graph, Edge

if TYPE_CHECKING:
    from .walker import SymbolTable

@dataclass
class TokenCount:
    operators: Set[str] = field(default_factory=set)
    operands: Set[str] = field(default_factory=set)
    total_operators: int = 0
    total_operands: int = 0

def gather_operators_and_operands(cursor: Cursor) -> TokenCount:
    count = TokenCount()
    try:
        tokens = list(cursor.get_tokens())
    except Exception:
        return count

    for token in tokens:
        kind = token.kind
        spelling = token.spelling
        
        if kind in (TokenKind.PUNCTUATION, TokenKind.KEYWORD):
            count.operators.add(spelling)
            count.total_operators += 1
        elif kind in (TokenKind.IDENTIFIER, TokenKind.LITERAL):
            count.operands.add(spelling)
            count.total_operands += 1
            
    return count

@dataclass
class HalsteadMetrics:
    element_id: str
    element_kind: str
    n1: int
    n2: int
    N1: int
    N2: int
    vocabulary: int
    length: int
    volume: float
    difficulty: float
    effort: float
    estimated_bugs: float

    @classmethod
    def from_counts(cls, element_id: str, element_kind: str, n1: int, n2: int, N1: int, N2: int) -> 'HalsteadMetrics':
        vocabulary = n1 + n2
        length = N1 + N2
        volume = length * (math.log2(vocabulary) if vocabulary > 0 else 0)
        difficulty = (n1 / 2.0) * (N2 / n2 if n2 > 0 else 0)
        effort = difficulty * volume
        estimated_bugs = volume / 3000.0

        return cls(
            element_id=element_id,
            element_kind=element_kind,
            n1=n1,
            n2=n2,
            N1=N1,
            N2=N2,
            vocabulary=vocabulary,
            length=length,
            volume=volume,
            difficulty=difficulty,
            effort=effort,
            estimated_bugs=estimated_bugs
        )

    @classmethod
    def aggregate(cls, element_id: str, element_kind: str, metrics: List['HalsteadMetrics']) -> 'HalsteadMetrics':
        total_length = sum(m.length for m in metrics)
        total_volume = sum(m.volume for m in metrics)
        total_effort = sum(m.effort for m in metrics)
        estimated_bugs = total_volume / 3000.0

        return cls(
            element_id=element_id,
            element_kind=element_kind,
            n1=0,
            n2=0,
            N1=0,
            N2=0,
            vocabulary=-1,
            length=total_length,
            volume=total_volume,
            difficulty=float('nan'),
            effort=total_effort,
            estimated_bugs=estimated_bugs
        )

    def to_map(self, replace_nan_with: float = -1.0) -> dict:
        def _safe(val):
            if isinstance(val, float) and math.isnan(val):
                return replace_nan_with
            return val

        # Note: keys must match java's HalsteadMetrics.toMap() exactly
        return {
            "vocabulary": self.vocabulary,
            "length": self.length,
            "volume": _safe(self.volume),
            "difficulty": _safe(self.difficulty),
            "effort": _safe(self.effort),
            "estimatedBugs": _safe(self.estimated_bugs),
        }

def inject_halstead(graph: Graph, symbol_table: SymbolTable, file_nodes: Dict[str, Node]):
    metrics: List[HalsteadMetrics] = []
    by_usr: Dict[str, HalsteadMetrics] = {}
    
    # 1. Base metrics for Operation / Variable
    for usr, observations in symbol_table.by_usr.items():
        canonical = None
        for obs in observations:
            if obs.is_definition:
                canonical = obs
                break
        if canonical is None:
            canonical = observations[0]
            
        if getattr(canonical, 'halstead_tokens', None) is not None:
            t = canonical.halstead_tokens
            m = HalsteadMetrics.from_counts(
                element_id=usr,
                element_kind=canonical.sabo_label,
                n1=len(t.operators),
                n2=len(t.operands),
                N1=t.total_operators,
                N2=t.total_operands
            )
            metrics.append(m)
            by_usr[usr] = m

    # 2. Dual-Path Aggregation
    type_aggregates: Dict[str, List[HalsteadMetrics]] = {}
    file_aggregates: Dict[str, List[HalsteadMetrics]] = {}
    
    for usr, m in by_usr.items():
        canonical = symbol_table.canonical(usr)
        
        # Object-Oriented Path
        if canonical.parent_label == "Type" and canonical.parent_usr:
            type_aggregates.setdefault(canonical.parent_usr, []).append(m)
        else:
            # File-Based Path
            if canonical.file_path:
                file_aggregates.setdefault(canonical.file_path, []).append(m)
                
    scope_aggregates: Dict[str, List[HalsteadMetrics]] = {}
    
    # Aggregate Types -> Scope
    for type_usr, type_metrics in type_aggregates.items():
        if type_metrics:
            m = HalsteadMetrics.aggregate(type_usr, "Type", type_metrics)
            metrics.append(m)
            
            # Find Type's parent Scope
            current_parent_usr = None
            current_parent_label = None
            obs_list = symbol_table.by_usr.get(type_usr, [])
            if obs_list:
                for obs in obs_list:
                    if obs.is_definition:
                        current_parent_usr = obs.parent_usr
                        current_parent_label = obs.parent_label
                        break
                if current_parent_usr is None:
                    current_parent_usr = obs_list[0].parent_usr
                    current_parent_label = obs_list[0].parent_label
                
            if current_parent_label == "Scope" and current_parent_usr:
                scope_aggregates.setdefault(current_parent_usr, []).append(m)
                
    # Aggregate Scopes
    for scope_usr, s_metrics in scope_aggregates.items():
        if s_metrics:
            metrics.append(HalsteadMetrics.aggregate(scope_usr, "Scope", s_metrics))
            
    # Aggregate Files -> Folders
    folder_aggregates: Dict[str, List[HalsteadMetrics]] = {}
    
    # Build reverse contains map from graph
    # child_id -> parent_id (only for Folder -contains-> File/Folder)
    parent_map = {}
    for edge in graph.edges:
        if edge.label == "contains":
            parent_map[edge.source_id] = edge.target_id
            
    for file_path, f_metrics in file_aggregates.items():
        if f_metrics:
            file_node = file_nodes.get(file_path)
            if file_node:
                m = HalsteadMetrics.aggregate(file_node.id, "File", f_metrics)
                metrics.append(m)
                
                parent_folder_id = parent_map.get(file_node.id)
                if parent_folder_id:
                    folder_aggregates.setdefault(parent_folder_id, []).append(m)

    # Folders -> parent Folders
    # Process bottom-up by path length (deepest folders first)
    # folder IDs are relative paths (like "a/b/c" or ".")
    sorted_folders = sorted(folder_aggregates.keys(), key=lambda x: len(x.split('/')), reverse=True)
    
    for folder_id in sorted_folders:
        fo_metrics = folder_aggregates[folder_id]
        if fo_metrics:
            m = HalsteadMetrics.aggregate(folder_id, "Folder", fo_metrics)
            metrics.append(m)
            
            parent_folder_id = parent_map.get(folder_id)
            if parent_folder_id:
                folder_aggregates.setdefault(parent_folder_id, []).append(m)
                # Need to re-sort? No, because parent will always be shorter and thus processed later,
                # as long as we add it to the aggregates before we reach it in the iteration.
                # BUT wait, sorted_folders is already built. If parent is not in sorted_folders, 
                # we must add it and ensure it gets processed.
                # Actually, a safer topological sort is to process leaves first.
    
    # Let's fix folder traversal:
    from collections import deque
    
    # Calculate in-degrees for bottom-up traversal
    children_map = {}
    for edge in graph.edges:
        if edge.label == "contains":
            children_map.setdefault(edge.source_id, []).append(edge.target_id)
            
    # Actually, the simplest way is to do a recursive compute.
    folder_metrics_computed: Dict[str, HalsteadMetrics] = {}
    
    def compute_folder_metrics(fid: str) -> Optional[HalsteadMetrics]:
        if fid in folder_metrics_computed:
            return folder_metrics_computed[fid]
            
        child_metrics = list(folder_aggregates.get(fid, []))
        for child_id in children_map.get(fid, []):
            child_node = next((n for n in graph.nodes if n.id == child_id), None)
            if child_node and "Folder" in child_node.labels:
                child_m = compute_folder_metrics(child_id)
                if child_m:
                    child_metrics.append(child_m)
                    
        if child_metrics:
            m = HalsteadMetrics.aggregate(fid, "Folder", child_metrics)
            folder_metrics_computed[fid] = m
            return m
        return None
        
    # Find root folders (Project node contains them)
    # The root folder ID is "." usually, but we can just run for all folders.
    for n in graph.nodes:
        if "Folder" in n.labels:
            m = compute_folder_metrics(n.id)
            if m and m not in metrics:
                metrics.append(m)
            
    # 3. Inject Metrics#HalsteadMetrics node and edges
    halstead_node = Node("Metrics#HalsteadMetrics", "Metric")
    halstead_node.properties["simpleName"] = "HalsteadMetrics"
    halstead_node.properties["qualifiedName"] = "Halstead Complexity Metrics"
    halstead_node.properties["kind"] = "metric"
    graph.add_node(halstead_node)
    
    for m in metrics:
        edge = Edge(m.element_id, halstead_node.id, "measures")
        edge.properties.update(m.to_map())
        graph.add_edge(edge)
