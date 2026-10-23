import type { ReactNode } from "react";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import { cn } from "../lib/utils";

type Id = string | number;

/** Drag-and-drop (pointer and keyboard) context for a vertical list of `SortableItem`s. */
export function SortableList({
  ids,
  onReorder,
  children,
}: {
  ids: Id[];
  /** the ids in their new order */
  onReorder: (ids: Id[]) => void;
  children: ReactNode;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), // links and buttons still click
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    onReorder(arrayMove(ids, ids.indexOf(active.id), ids.indexOf(over.id)));
  };
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  );
}

/** A `<li>` with a drag handle in front of its content. */
export function SortableItem({
  id,
  label,
  className,
  children,
}: {
  id: Id;
  /** what moves, for screen readers */
  label: string;
  className?: string;
  children: ReactNode;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(className, isDragging && "relative z-10 bg-surface shadow-md")}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Drag ${label} to reorder`}
        className="shrink-0 cursor-grab touch-none rounded-md p-1 text-faint hover:bg-tint hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <GripVertical className="h-4 w-4" aria-hidden="true" />
      </button>
      {children}
    </li>
  );
}
