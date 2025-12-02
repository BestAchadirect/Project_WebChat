import React from 'react';
import { MagentoConfigForm } from '../components/magento/MagentoConfigForm';

export const MagentoSettingsPage: React.FC = () => {
    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold text-gray-900">Magento Settings</h1>
                <p className="mt-2 text-gray-600">
                    Configure your Magento store integration
                </p>
            </div>

            <MagentoConfigForm />

            {/* Additional Info */}
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-6">
                <h3 className="text-sm font-semibold text-blue-900 mb-2">
                    How to get your Magento API credentials
                </h3>
                <ol className="list-decimal list-inside space-y-1 text-sm text-blue-800">
                    <li>Log in to your Magento Admin Panel</li>
                    <li>Navigate to System → Integrations</li>
                    <li>Create a new integration with API access</li>
                    <li>Copy the Consumer Key and Consumer Secret</li>
                    <li>Paste them in the fields above</li>
                </ol>
            </div>
        </div>
    );
};
