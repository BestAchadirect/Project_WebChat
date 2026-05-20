type EmptyStateProps = {
    title: string;
    description: string;
};

export const EmptyState = ({ title, description }: EmptyStateProps): JSX.Element => {
    return (
        <div className="flex h-full min-h-72 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center shadow-sm">
            <div className="max-w-md space-y-2">
                <div className="mx-auto h-10 w-10 rounded-full bg-slate-100" />
                <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
                <p className="text-sm text-slate-500">{description}</p>
            </div>
        </div>
    );
};
