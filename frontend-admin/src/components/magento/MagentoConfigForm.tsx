import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { tenantsApi } from '../../api/tenants';
import { useToast } from '../../hooks/useToast';
import { Button } from '../common/Button';
import { Input } from '../common/Input';

const magentoSchema = z.object({
    magentoUrl: z.string().url('Invalid URL'),
    magentoApiKey: z.string().min(1, 'API Key is required'),
    magentoApiSecret: z.string().min(1, 'API Secret is required'),
});

type MagentoFormData = z.infer<typeof magentoSchema>;

export const MagentoConfigForm: React.FC = () => {
    const [isTesting, setIsTesting] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const { showToast } = useToast();

    const {
        register,
        handleSubmit,
        formState: { errors },
        getValues,
    } = useForm<MagentoFormData>({
        resolver: zodResolver(magentoSchema),
    });

    const handleTestConnection = async () => {
        const values = getValues();
        setIsTesting(true);
        try {
            const result = await tenantsApi.testMagentoConnection(
                values.magentoUrl,
                values.magentoApiKey,
                values.magentoApiSecret
            );
            if (result.success) {
                showToast('Connection successful!', 'success');
            } else {
                showToast(result.message || 'Connection failed', 'error');
            }
        } catch (error: any) {
            showToast(error.response?.data?.message || 'Connection test failed', 'error');
        } finally {
            setIsTesting(false);
        }
    };

    const onSubmit = async (data: MagentoFormData) => {
        setIsSaving(true);
        try {
            await tenantsApi.updateTenantSettings(data);
            showToast('Settings saved successfully', 'success');
        } catch (error: any) {
            showToast(error.response?.data?.message || 'Save failed', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="bg-white rounded-xl shadow-sm p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-6">Magento Configuration</h3>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
                <Input
                    label="Magento Store URL"
                    type="url"
                    placeholder="https://your-store.com"
                    error={errors.magentoUrl?.message}
                    helperText="The base URL of your Magento store"
                    {...register('magentoUrl')}
                />

                <Input
                    label="API Key"
                    type="text"
                    placeholder="Your Magento API key"
                    error={errors.magentoApiKey?.message}
                    {...register('magentoApiKey')}
                />

                <Input
                    label="API Secret"
                    type="password"
                    placeholder="Your Magento API secret"
                    error={errors.magentoApiSecret?.message}
                    {...register('magentoApiSecret')}
                />

                <div className="flex gap-3">
                    <Button
                        type="button"
                        variant="ghost"
                        onClick={handleTestConnection}
                        isLoading={isTesting}
                    >
                        Test Connection
                    </Button>
                    <Button type="submit" isLoading={isSaving}>
                        Save Settings
                    </Button>
                </div>
            </form>
        </div>
    );
};
